// Network page: renders the measurement snapshot in network.json.
const $ = (s) => document.querySelector(s)
const fmt = (n) => (n === null || n === undefined ? '–' : Number(n).toLocaleString('en-US'))
const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(1)}%` : '–')
const dur = (s) => {
  if (s === null || s === undefined) return '–'
  if (s < 120) return `${Math.round(s)} s`
  if (s < 7200) return `${Math.round(s / 60)} min`
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`
  return `${Math.round(s / 86400)} d`
}

function tile(value, label, note) {
  const d = document.createElement('div')
  d.className = 'tile'
  d.innerHTML = `<div class="tile-value"></div><div class="tile-label"></div><div class="muted small"></div>`
  d.children[0].textContent = value
  d.children[1].textContent = label
  d.children[2].textContent = note || ''
  return d
}

function bars(rows) {
  const max = Math.max(...rows.map((r) => r.labels))
  const wrap = $('#volume')
  wrap.replaceChildren()
  for (const r of rows) {
    const row = document.createElement('div')
    row.className = 'hbar'
    row.title = `${r.handle}: ${fmt(r.labels)} labels, ${fmt(r.active)} in force`
    const name = document.createElement('span')
    name.className = 'hbar-name'
    name.textContent = r.handle
    const track = document.createElement('span')
    track.className = 'hbar-track'
    const fill = document.createElement('span')
    fill.className = 'hbar-fill'
    fill.style.width = `${(100 * r.labels) / max}%`
    track.append(fill)
    const val = document.createElement('span')
    val.className = 'hbar-val'
    val.textContent = fmt(r.labels)
    row.append(name, track, val)
    wrap.append(row)
  }
}

const LENS_NAMES = { public: 'Logged-out visitor', popular: 'Popular stack', protective: 'Protective stack', all: 'Every labeler that labelled it' }

function lensTable(lenses) {
  const t = $('#lens-table')
  const head = document.createElement('tr')
  for (const h of ['', 'Hidden', 'Warned', 'Info badge', 'As is']) {
    const th = document.createElement('th')
    th.textContent = h
    head.append(th)
  }
  const rows = [head]
  for (const [kind, title] of [['post', 'Posts'], ['account', 'Accounts']]) {
    const L = lenses[kind]
    const tr = document.createElement('tr')
    const th = document.createElement('th')
    th.colSpan = 5
    th.textContent = `${title} (sample of ${fmt(L.n)})`
    tr.append(th)
    rows.push(tr)
    // The leave-one-out lens that moves the protective stack furthest back towards the
    // logged-out view shows how much of its effect one service carries.
    const loo = Object.keys(L.differs_from_public || {}).filter((k) => k.startsWith('protective_minus_'))
    const minus = loo.sort((x, y) => L.differs_from_public[x] - L.differs_from_public[y])[0]
    const names = { ...LENS_NAMES, ...(minus ? { [minus]: 'Protective stack without its most influential labeler' } : {}) }
    for (const lens of ['public', 'popular', 'protective', ...(minus && L.outcomes[minus] ? [minus] : []), 'all']) {
      const o = L.outcomes[lens]
      const r = document.createElement('tr')
      const cells = [names[lens], pct(o.hidden || 0, L.n), pct((o.blurred || 0) + (o.alert || 0), L.n), pct(o.inform || 0, L.n), pct(o.plain || 0, L.n)]
      for (const c of cells) {
        const td = document.createElement('td')
        td.textContent = c
        r.append(td)
      }
      rows.push(r)
    }
  }
  t.replaceChildren(...rows)
}

const COLUMNS = [
  ['handle', 'Labeler', (r) => r.handle || r.did],
  ['category', 'Kind', (r) => r.category],
  ['likes', 'Likes', (r) => fmt(r.likes)],
  ['labels', 'Labels', (r) => fmt(r.labels) + (r.windowed ? ' (window)' : '') + (r.complete_known && !r.complete ? ' (incomplete)' : '')],
  ['active', 'In force', (r) => fmt(r.active)],
  ['retract', 'Retracted', (r) => pct(r.retracted_pairs, r.retracted_pairs + r.active)],
  ['inert', 'Undeclared', (r) => pct(r.inert, r.labels)],
  ['latency', 'Median time to label a post', (r) => dur(r.latency_s?.p50)],
  ['browser', 'Browser-readable', (r) => (r.browser ? 'yes' : 'no')],
]

let sortKey = 'labels', sortDir = -1, rows = []

function sortValue(r, k) {
  if (k === 'retract') return r.retracted_pairs / Math.max(1, r.retracted_pairs + r.active)
  if (k === 'inert') return r.inert / Math.max(1, r.labels)
  if (k === 'latency') return r.latency_s?.p50 ?? Infinity
  if (k === 'browser') return r.browser ? 1 : 0
  return r[k] ?? ''
}

function table() {
  const t = $('#table')
  const sorted = [...rows].sort((a, b) => {
    const x = sortValue(a, sortKey), y = sortValue(b, sortKey)
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir
  })
  const head = document.createElement('tr')
  for (const [k, title] of COLUMNS) {
    const th = document.createElement('th')
    const b = document.createElement('button')
    b.type = 'button'
    b.textContent = title + (k === sortKey ? (sortDir < 0 ? ' ↓' : ' ↑') : '')
    b.onclick = () => { sortDir = k === sortKey ? -sortDir : -1; sortKey = k; table() }
    th.append(b)
    head.append(th)
  }
  const body = sorted.map((r) => {
    const tr = document.createElement('tr')
    for (const [, , f] of COLUMNS) {
      const td = document.createElement('td')
      td.textContent = f(r)
      tr.append(td)
    }
    return tr
  })
  t.replaceChildren(head, ...body)
}

async function boot() {
  const d = await (await fetch('network.json')).json()
  rows = Object.entries(d.per_labeler).map(([did, r]) => ({ did, ...r }))
  const s = d.summary
  $('#tiles').replaceChildren(
    tile(fmt(s.declared), 'labeling services declared', `${fmt(s.resolvable)} publish an endpoint`),
    tile(pct(s.answering, s.resolvable), 'endpoints answer queries', `${fmt(s.answering)} of ${fmt(s.resolvable)}`),
    tile(pct(s.browser, s.answering), 'of those let a browser read them', 'the rest need a server-side client'),
    tile(fmt(s.labels), 'labels collected', `${fmt(s.collected)} services`),
    tile(pct(s.inert, s.labels), 'labels have no effect', 'their value was never declared, so clients ignore them'),
  )
  const top = [...rows].sort((a, b) => b.labels - a.labels).slice(0, 15)
  $('#volume-note').textContent = `The 15 largest of ${rows.length} services. Services whose stream had passed sequence number three million were collected from a recent window, so their bars count that window only; services whose stream ended before its latest label are marked incomplete in the table. Hover for labels in force.`
  bars(top)
  lensTable(d.lenses)
  table()
  $('#foot').textContent = `Snapshot ${d.generated}. Aggregate figures only; no labelled accounts or posts are listed.`
}

boot()
