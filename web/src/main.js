// LabelLens: ask every Bluesky labeler about one post or account, then show
// how the post would look under different labeler subscriptions.
// Deep imports keep the bundle to the moderation code instead of the whole API client.
import {
  moderatePost,
  moderateProfile,
  interpretLabelValueDefinitions,
} from '../node_modules/@atproto/api/dist/moderation/index.js'
import { DEFAULT_LABEL_SETTINGS, LABELS } from '../node_modules/@atproto/api/dist/moderation/const/labels.js'
import { CUSTOM_LABEL_VALUE_RE } from '../node_modules/@atproto/api/dist/moderation/types.js'
import { BSKY_LABELER_DID } from '../node_modules/@atproto/api/dist/const.js'

const APPVIEW = 'https://public.api.bsky.app/xrpc'
const QUERY_TIMEOUT_MS = 4000 // first pass, for services that answered at the last measurement
const SLOW_TIMEOUT_MS = 8000 // second chance for those that did not answer in the first pass
const RECHECK_TIMEOUT_MS = 4000 // for services that were offline at the last measurement
const PARALLEL = 32
const MAX_SUBSCRIBED = 20 // Bluesky clients cap third-party labeler subscriptions
const VIEWER_DID = 'did:example:labellens-viewer' // stands in for a signed-in viewer

const $ = (sel) => document.querySelector(sel)
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v)
    else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v)
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue
    n.append(k instanceof Node ? k : document.createTextNode(String(k)))
  }
  return n
}

// Example items chosen from the measurement data; see src/pick_examples.py.
const EXAMPLES = [
  { title: 'The New York Times', target: 'nytimes.com' },
  { title: 'Bluesky', target: 'bsky.app' },
]

const CATEGORY_NAMES = { protective: 'protective', descriptive: 'descriptive', undeclared: 'no declared labels' }

let directory = [] // labelers shipped with the app
let byDid = new Map()
let snapshot = null // static fallback for labelers without CORS, see src/build_snapshot.py

// The published snapshot covers only the example accounts (data/snapshot_subjects.txt);
// a local build without a subjects list covers everyone.
const snapshotCovers = (did) => Boolean(snapshot) && (!snapshot.subjects || snapshot.subjects.includes(did))
let current = null // state of the inspection on screen
let runId = 0

// ---------- input parsing ----------

async function resolveHandle(handle) {
  if (handle.startsWith('did:')) return handle
  const r = await getJson(`${APPVIEW}/com.atproto.identity.resolveHandle?handle=${encodeURIComponent(handle)}`)
  return r.did
}

async function parseTarget(raw) {
  let s = raw.trim()
  if (!s) throw new Error('Paste a Bluesky post link, an at:// URI or a handle.')
  s = s.replace(/^@/, '')
  let m = s.match(/bsky\.app\/profile\/([^/?#]+)\/post\/([^/?#]+)/)
  if (m) return { kind: 'post', uri: `at://${await resolveHandle(m[1])}/app.bsky.feed.post/${m[2]}` }
  m = s.match(/bsky\.app\/profile\/([^/?#]+)\/?$/)
  if (m) return { kind: 'account', did: await resolveHandle(m[1]) }
  m = s.match(/^at:\/\/([^/]+)\/app\.bsky\.feed\.post\/([^/?#]+)/)
  if (m) return { kind: 'post', uri: `at://${await resolveHandle(m[1])}/app.bsky.feed.post/${m[2]}` }
  m = s.match(/^at:\/\/([^/]+)\/?$/)
  if (m) return { kind: 'account', did: await resolveHandle(m[1]) }
  if (/^did:[a-z]+:[A-Za-z0-9._:%-]+$/.test(s) || /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(s))
    return { kind: 'account', did: await resolveHandle(s) }
  throw new Error('That does not look like a Bluesky post link, at:// URI or handle.')
}

async function getJson(url, opts = {}) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let msg = `${r.status}`
    try { msg = (await r.json()).message || msg } catch {}
    throw new Error(msg)
  }
  return r.json()
}

// ---------- census ----------

async function queryLabeler(lab, uris, signal, timeoutMs) {
  const qs = uris.map((u) => `uriPatterns=${encodeURIComponent(u)}`).join('&')
  const url = `${lab.endpoint}/xrpc/com.atproto.label.queryLabels?${qs}&limit=250`
  const t0 = performance.now()
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  signal.addEventListener('abort', () => ctrl.abort())
  try {
    const r = await fetch(url, { signal: ctrl.signal })
    if (!r.ok) return { lab, status: 'error', detail: `HTTP ${r.status}`, ms: performance.now() - t0 }
    const body = await r.json()
    return { lab, status: 'ok', labels: body.labels || [], ms: performance.now() - t0 }
  } catch (e) {
    const timeout = ctrl.signal.aborted && !signal.aborted
    return { lab, status: timeout ? 'timeout' : 'error', detail: timeout ? `no answer in ${timeoutMs / 1000} s` : 'unreachable', ms: performance.now() - t0 }
  } finally {
    clearTimeout(timer)
  }
}

// Fold a labeler's raw label log into the labels in force now.
function activeLabels(raw, now = Date.now()) {
  const latest = new Map()
  for (const l of raw) {
    const k = `${l.src}|${l.uri}|${l.val}`
    const prev = latest.get(k)
    if (!prev || (l.cts || '') >= (prev.cts || '')) latest.set(k, l)
  }
  const active = [], retracted = [], expired = []
  for (const l of latest.values()) {
    if (l.neg) retracted.push(l)
    else if (l.exp && Date.parse(l.exp) < now) expired.push(l)
    else active.push(l)
  }
  return { active, retracted, expired }
}

// Labels in force at collection time for services a browser cannot query.
async function snapshotFor(did, uris) {
  const bySrc = new Map()
  if (!snapshotCovers(did)) return bySrc
  const hash = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(did))
  const key = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, snapshot.shard_chars)
  let shard = {}
  try { shard = await getJson(`snapshot/${key}.json`) } catch {}
  for (const [i, rest, val, cts] of shard[did] || []) {
    const uri = rest ? `at://${did}${rest}` : did
    if (!uris.includes(uri)) continue
    const src = snapshot.sources[i]
    if (!bySrc.has(src)) bySrc.set(src, [])
    bySrc.get(src).push({ src, uri, val, cts })
  }
  return bySrc
}

// Ask the given labelers, appending to results; snap is the snapshot lookup for the subject.
async function runCensus(labs, uris, snap, covered, results, onResult, signal, timeoutMs) {
  const queue = [...labs]
  const fromSnapshot = (lab) => covered
    ? { lab, status: 'snapshot', labels: snap.get(lab.did) || [], ms: 0 }
    : { lab, status: 'nocors', detail: 'does not allow browser queries', ms: 0 }
  async function worker() {
    while (queue.length && !signal.aborted) {
      const lab = queue.shift()
      let res
      if (lab.browser === false && snapshot?.srcSet.has(lab.did)) res = fromSnapshot(lab)
      else {
        res = await queryLabeler(lab, uris, signal, timeoutMs)
        if (res.status !== 'ok' && snapshot?.srcSet.has(lab.did)) res = fromSnapshot(lab)
      }
      if (signal.aborted) return
      if (res.status === 'ok' || res.status === 'snapshot') {
        // Some services answer for several labelers; keep only the labeler's own labels,
        // the others are asked at their own entry.
        res.labels = res.labels.filter((l) => uris.includes(l.uri) && l.src === lab.did)
        Object.assign(res, activeLabels(res.labels))
      }
      results.push(res)
      onResult(res, results)
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker))
  return results
}

async function fetchDefinitions(dids) {
  const defs = {}
  const views = {}
  for (let i = 0; i < dids.length; i += 20) {
    const qs = dids.slice(i, i + 20).map((d) => `dids=${encodeURIComponent(d)}`).join('&')
    try {
      const r = await getJson(`${APPVIEW}/app.bsky.labeler.getServices?${qs}&detailed=true`)
      for (const v of r.views || []) {
        views[v.creator.did] = v
        defs[v.creator.did] = interpretLabelValueDefinitions(v)
      }
    } catch {}
  }
  return { defs, views }
}

// ---------- lenses ----------

function lensPresets(census) {
  const said = census.filter((r) => isAnswer(r) && r.active.length).map((r) => r.lab.did)
  const others = directory.filter((l) => l.did !== BSKY_LABELER_DID) // sorted by likes
  const popular = others.slice(0, MAX_SUBSCRIBED).map((l) => l.did)
  const protective = others.filter((l) => l.category === 'protective').slice(0, MAX_SUBSCRIBED).map((l) => l.did)
  return [
    { id: 'public', title: 'Logged-out visitor', note: 'Public web view and embeds: only Bluesky’s own moderation service applies.', userDid: undefined, labelers: [] },
    { id: 'popular', title: 'Popular stack', note: `Signed-in user subscribed to the ${popular.length} most-liked labelers.`, userDid: VIEWER_DID, labelers: popular },
    { id: 'protective', title: 'Protective stack', note: `Signed-in user subscribed to the ${protective.length} most-liked labelers that hide or warn.`, userDid: VIEWER_DID, labelers: protective },
    { id: 'custom', title: 'Your stack', note: 'Pick labelers below. Starts with every labeler that labelled this item.', userDid: VIEWER_DID, labelers: said.filter((d) => d !== BSKY_LABELER_DID).slice(0, MAX_SUBSCRIBED), editable: true },
  ]
}

function moderationPrefs(lens) {
  return {
    adultContentEnabled: false,
    labels: { ...DEFAULT_LABEL_SETTINGS },
    labelers: [BSKY_LABELER_DID, ...lens.labelers].map((did) => ({ did, labels: {} })),
    mutedWords: [],
    hiddenPosts: [],
  }
}

function decide(lens) {
  const { subject, labels, defs } = current
  const opts = { userDid: lens.userDid, prefs: moderationPrefs(lens), labelDefs: defs }
  const accountLabels = labels.filter((l) => l.uri === subject.did || l.uri.endsWith('/app.bsky.actor.profile/self'))
  const selfLabels = (subject.post?.labels || []).filter((l) => l.src === subject.did)
  if (subject.kind === 'post') {
    const post = structuredClone(subject.post)
    post.labels = [...selfLabels, ...labels.filter((l) => l.uri === subject.uri)]
    post.author = { ...post.author, labels: accountLabels }
    return { ui: moderatePost(post, opts).ui('contentList'), where: 'feed' }
  }
  const profile = { ...subject.profile, labels: accountLabels }
  return { ui: moderateProfile(profile, opts).ui('profileList'), where: 'profile list' }
}

function causeText(c) {
  if (c.type !== 'label') return c.type
  const lab = byDid.get(c.label.src)
  const loc = c.labelDef.locales?.find((l) => l.lang?.startsWith('en')) || c.labelDef.locales?.[0]
  const name = loc?.name || c.label.val
  const who = c.label.src === BSKY_LABELER_DID ? 'Bluesky Moderation' : (lab?.name || lab?.handle || c.label.src)
  return `${name} · ${who}`
}

function outcome(ui) {
  if (ui.filter) return { cls: 'hidden', head: 'Hidden', body: 'Removed from feeds and search results.', causes: ui.filters }
  if (ui.blur) return { cls: 'blurred', head: 'Behind a warning', body: 'Shown collapsed; the reader must click to see it.', causes: ui.blurs }
  if (ui.alert) return { cls: 'alert', head: 'Shown with a warning badge', body: '', causes: ui.alerts }
  if (ui.inform) return { cls: 'inform', head: 'Shown with an info badge', body: '', causes: ui.informs }
  return { cls: 'plain', head: 'Shown as is', body: 'No subscribed labeler changes how it looks.', causes: [] }
}

// ---------- rendering ----------

function subjectCard() {
  const { subject } = current
  if (subject.kind === 'post') {
    const p = subject.post
    return el('div', { class: 'subject' },
      el('div', { class: 'subject-head' },
        p.author.avatar ? el('img', { src: p.author.avatar, alt: '', class: 'avatar' }) : el('div', { class: 'avatar' }),
        el('div', {}, el('strong', {}, p.author.displayName || p.author.handle), el('div', { class: 'muted' }, `@${p.author.handle}`))),
      el('p', { class: 'subject-text' }, p.record?.text || '(no text)'),
      p.embed?.images?.length ? el('p', { class: 'muted' }, `${p.embed.images.length} image(s)`) : null,
      el('a', { href: bskyLink(), target: '_blank', rel: 'noopener' }, 'Open on Bluesky'))
  }
  const a = subject.profile
  return el('div', { class: 'subject' },
    el('div', { class: 'subject-head' },
      a.avatar ? el('img', { src: a.avatar, alt: '', class: 'avatar' }) : el('div', { class: 'avatar' }),
      el('div', {}, el('strong', {}, a.displayName || a.handle), el('div', { class: 'muted' }, `@${a.handle}`))),
    a.description ? el('p', { class: 'subject-text' }, a.description) : null,
    el('a', { href: bskyLink(), target: '_blank', rel: 'noopener' }, 'Open on Bluesky'))
}

function bskyLink() {
  const s = current.subject
  if (s.kind === 'post') return `https://bsky.app/profile/${s.did}/post/${s.uri.split('/').pop()}`
  return `https://bsky.app/profile/${s.did}`
}

const isAnswer = (r) => r.status === 'ok' || r.status === 'snapshot'

function renderProgress(results) {
  const ok = results.filter(isAnswer)
  const snap = results.filter((r) => r.status === 'snapshot').length
  const blocked = results.filter((r) => r.status === 'nocors').length
  const speaking = ok.filter((r) => r.active.length)
  const failed = results.length - ok.length
  const pct = Math.round((100 * results.length) / directory.length)
  $('#progress').replaceChildren(
    el('div', { class: 'bar' }, el('span', { style: `width:${pct}%` })),
    el('p', {},
      el('strong', {}, `${results.length} of ${directory.length}`), ' labelers asked · ',
      el('strong', {}, ok.length), ' answered', snap ? ` (${snap} from the ${snapshot.generated.slice(0, 10)} snapshot)` : '', ' · ',
      el('strong', {}, failed), ' unreachable', blocked ? ` (${blocked} of them do not allow browser queries)` : '', ' · ',
      el('strong', { class: 'accent' }, speaking.length), ' have a label on it'))
}

function renderCensus(results) {
  const ok = results.filter(isAnswer)
  const rows = ok.filter((r) => r.active.length || r.retracted.length || r.expired.length)
    .sort((a, b) => b.active.length - a.active.length || (b.lab.likes - a.lab.likes))
  const list = el('div', { class: 'census' })
  if (!rows.length) list.append(el('p', { class: 'empty' }, 'No labeler has labelled this item. Every lens below shows it as is.'))
  for (const r of rows) {
    const defs = current.defs[r.lab.did] || []
    const chip = (l, state) => {
      const d = defs.find((x) => x.identifier === l.val)
      const known = Boolean((CUSTOM_LABEL_VALUE_RE.test(l.val) && d) || LABELS[l.val])
      const loc = d?.locales?.find((x) => x.lang?.startsWith('en')) || d?.locales?.[0]
      const target = l.uri === current.subject.did || l.uri.endsWith('/app.bsky.actor.profile/self') ? 'account' : 'post'
      return el('span', {
        class: `chip ${state} ${d?.severity || ''} ${known ? '' : 'undeclared'}`,
        title: [loc?.description, `on the ${target}`, l.cts && `issued ${l.cts.slice(0, 10)}`, !known && 'not declared by this labeler, so clients ignore it'].filter(Boolean).join(' · '),
      }, loc?.name || l.val, target === 'account' ? el('small', {}, ' account') : null)
    }
    list.append(el('div', { class: 'census-row' },
      el('div', { class: 'who' },
        el('strong', {}, r.lab.name || r.lab.handle || r.lab.did),
        el('span', { class: 'muted' }, ` @${r.lab.handle || r.lab.did}`),
        el('span', { class: `tag ${r.lab.category}` }, CATEGORY_NAMES[r.lab.category] || r.lab.category),
        r.status === 'snapshot' ? el('span', { class: 'tag', title: 'This service does not let browsers query it; labels come from the collected snapshot.' }, 'snapshot') : null),
      el('div', { class: 'chips' },
        r.active.map((l) => chip(l, 'active')),
        r.retracted.map((l) => chip(l, 'retracted')),
        r.expired.map((l) => chip(l, 'expired')))))
  }
  $('#census').replaceChildren(list)
}

function renderLenses() {
  const wrap = el('div', { class: 'lenses' })
  for (const lens of current.lenses) {
    const { ui, where } = decide(lens)
    const o = outcome(ui)
    const card = el('section', { class: `lens ${o.cls}` },
      el('h3', {}, lens.title),
      el('p', { class: 'muted small' }, lens.note),
      el('div', { class: 'verdict' }, el('strong', {}, o.head), o.body ? el('span', {}, ` ${o.body}`) : null),
      o.causes.length ? el('ul', { class: 'causes' }, [...new Set(o.causes.map(causeText))].map((t) => el('li', {}, t))) : null,
      el('p', { class: 'muted small' }, `As rendered in a ${where} by the official moderation rules (@atproto/api).`))
    if (lens.editable) card.append(stackEditor(lens))
    wrap.append(card)
  }
  $('#lenses').replaceChildren(wrap)
}

function stackEditor(lens) {
  const said = current.census.filter((r) => isAnswer(r) && r.active.length && r.lab.did !== BSKY_LABELER_DID)
  const box = el('details', { class: 'stack' }, el('summary', {}, `Subscribed: ${lens.labelers.length} labeler(s). Change`))
  if (!said.length) box.append(el('p', { class: 'muted small' }, 'No third-party labeler labelled this item.'))
  for (const r of said) {
    const on = lens.labelers.includes(r.lab.did)
    box.append(el('label', { class: 'pick' },
      el('input', {
        type: 'checkbox', checked: on, onchange: (e) => {
          if (e.target.checked) {
            if (lens.labelers.length >= MAX_SUBSCRIBED) { e.target.checked = false; return }
            lens.labelers.push(r.lab.did)
          } else lens.labelers = lens.labelers.filter((d) => d !== r.lab.did)
          renderLenses()
          $('#lenses details.stack').open = true
        },
      }),
      ` ${r.lab.name || r.lab.handle}`))
  }
  return box
}

function renderDisagreement() {
  const states = current.lenses.map((lens) => outcome(decide(lens).ui).cls)
  const distinct = new Set(states).size
  $('#lens-summary').textContent = distinct > 1
    ? `The ${states.length} lenses disagree: this ${current.subject.kind} is shown in ${distinct} different ways.`
    : `All ${states.length} lenses agree on how this ${current.subject.kind} is shown.`
}

// ---------- main flow ----------

async function finish(census) {
  current.census = census
  current.labels = census.filter(isAnswer).flatMap((r) => r.active)
  const speakers = [...new Set(census.filter((r) => isAnswer(r) && (r.active.length || r.retracted.length)).map((r) => r.lab.did))]
  const missing = speakers.filter((d) => !(d in current.defs))
  Object.assign(current.defs, (await fetchDefinitions(missing)).defs)
  current.lenses = lensPresets(census)
  renderCensus(census)
  renderLenses()
  renderDisagreement()
}

async function inspect(raw) {
  const id = ++runId
  current?.abort?.abort()
  const abort = new AbortController()
  $('#error').textContent = ''
  $('#results').hidden = false
  $('#census').replaceChildren(el('p', { class: 'muted' }, 'Asking every labeler…'))
  $('#lenses').replaceChildren()
  $('#lens-summary').textContent = ''
  try {
    const t = await parseTarget(raw)
    let subject
    if (t.kind === 'post') {
      const r = await getJson(`${APPVIEW}/app.bsky.feed.getPosts?uris=${encodeURIComponent(t.uri)}`)
      if (!r.posts?.length) throw new Error('Post not found. It may be deleted or hidden from logged-out viewers.')
      subject = { kind: 'post', uri: t.uri, did: r.posts[0].author.did, post: r.posts[0] }
    } else {
      const profile = await getJson(`${APPVIEW}/app.bsky.actor.getProfile?actor=${encodeURIComponent(t.did)}`)
      subject = { kind: 'account', did: t.did, profile }
    }
    if (id !== runId) return
    current = { subject, census: [], labels: [], defs: {}, lenses: [], abort }
    history.replaceState(null, '', `#${encodeURIComponent(raw.trim())}`)
    $('#subject').replaceChildren(subjectCard())
    const uris = subject.kind === 'post'
      ? [subject.uri, subject.did, `at://${subject.did}/app.bsky.actor.profile/self`]
      : [subject.did, `at://${subject.did}/app.bsky.actor.profile/self`]
    // Services that answered at the last measurement go first, so the lenses appear quickly;
    // the ones that were offline are rechecked afterwards with a shorter timeout.
    const known = (l) => l.live !== false || (snapshot?.srcSet.has(l.did) && l.browser === false)
    const first = directory.filter(known)
    const later = directory.filter((l) => !known(l))
    const snap = await snapshotFor(subject.did, uris)
    const covered = snapshotCovers(subject.did)
    const census = []
    const progress = (res, all) => { if (id === runId) renderProgress(all) }
    const t0 = performance.now()
    await runCensus(first, uris, snap, covered, census, progress, abort.signal, QUERY_TIMEOUT_MS)
    if (id !== runId) return
    current.seconds = (performance.now() - t0) / 1000
    await finish(census)
    $('#timing').textContent = `Census of the ${first.length} services that answered at the last measurement took ${current.seconds.toFixed(1)} s. Rechecking ${later.length} that were offline\u2026`
    // Slow services get a second, longer try while the offline ones are rechecked.
    const slow = census.filter((r) => r.status === 'timeout').map((r) => r.lab)
    census.splice(0, census.length, ...census.filter((r) => r.status !== 'timeout'))
    const before = census.filter(isAnswer).length
    await Promise.all([
      runCensus(slow, uris, snap, covered, census, progress, abort.signal, SLOW_TIMEOUT_MS),
      runCensus(later, uris, snap, covered, census, progress, abort.signal, RECHECK_TIMEOUT_MS),
    ])
    if (id !== runId) return
    const revived = census.filter(isAnswer).length - before
    if (revived) await finish(census)
    $('#timing').textContent = `Census of the ${first.length} services that answered at the last measurement took ${current.seconds.toFixed(1)} s; ` +
      `${revived} more answered on recheck (${((performance.now() - t0) / 1000).toFixed(1)} s in total).`
  } catch (e) {
    if (id === runId) {
      $('#error').textContent = e.message
      $('#results').hidden = true
    }
  }
}

async function boot() {
  const d = await getJson('labelers.json')
  directory = d.labelers
  byDid = new Map(directory.map((l) => [l.did, l]))
  try {
    snapshot = await getJson('snapshot/index.json')
    snapshot.srcSet = new Set(snapshot.sources)
  } catch {}
  $('#dir-count').textContent = directory.length
  $('#dir-date').textContent = d.generated
  $('#form').addEventListener('submit', (e) => { e.preventDefault(); inspect($('#target').value) })
  $('#examples').replaceChildren(...EXAMPLES.map((x) => el('button', {
    type: 'button', onclick: () => { $('#target').value = x.target; inspect(x.target) },
  }, x.title)))
  const hash = decodeURIComponent(location.hash.slice(1))
  if (hash) { $('#target').value = hash; inspect(hash) }
}

boot()
