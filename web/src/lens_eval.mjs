// Offline lens comparison over a sample of labelled subjects.
// Input (stdin, JSON lines): {"subject": did-or-post-uri, "did": author did, "labels": [label, ...]}
// Args: path to labeler definitions JSON ({did: labelerViewDetailed}), path to named stacks JSON ({name: [did]}).
// Output (stdout, JSON lines): {"subject", "kind", "public", <stack name>..., "all", and for posts <lens>_postonly}
import fs from 'node:fs'
import readline from 'node:readline'
import {
  moderatePost,
  moderateProfile,
  interpretLabelValueDefinitions,
} from '../node_modules/@atproto/api/dist/moderation/index.js'
import { DEFAULT_LABEL_SETTINGS } from '../node_modules/@atproto/api/dist/moderation/const/labels.js'
import { BSKY_LABELER_DID } from '../node_modules/@atproto/api/dist/const.js'

const VIEWER_DID = 'did:example:labellens-viewer'
const views = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const stacks = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
const labelDefs = Object.fromEntries(Object.entries(views).map(([did, v]) => [did, interpretLabelValueDefinitions(v)]))

const prefs = (labelers) => ({
  adultContentEnabled: false,
  labels: { ...DEFAULT_LABEL_SETTINGS },
  labelers: [BSKY_LABELER_DID, ...labelers].map((did) => ({ did, labels: {} })),
  mutedWords: [],
  hiddenPosts: [],
})

function verdict(ui) {
  if (ui.filter) return 'hidden'
  if (ui.blur) return 'blurred'
  if (ui.alert) return 'alert'
  if (ui.inform) return 'inform'
  return 'plain'
}

function judge(row, lens) {
  const opts = { userDid: lens.userDid, prefs: prefs(lens.labelers), labelDefs }
  const account = row.labels.filter((l) => l.uri === row.did || l.uri.endsWith('/app.bsky.actor.profile/self'))
  const author = { did: row.did, handle: 'handle.invalid', labels: account, viewer: {} }
  if (row.subject.includes('/app.bsky.feed.post/')) {
    const post = {
      uri: row.subject, cid: 'bafy', author, record: { $type: 'app.bsky.feed.post', text: '', createdAt: '' },
      indexedAt: '', labels: row.labels.filter((l) => l.uri === row.subject), viewer: {},
    }
    return verdict(moderatePost(post, opts).ui('contentList'))
  }
  return verdict(moderateProfile(author, opts).ui('profileList'))
}

const lenses = { public: { userDid: undefined, labelers: [] } }
for (const [name, labelers] of Object.entries(stacks)) lenses[name] = { userDid: VIEWER_DID, labelers }

const rl = readline.createInterface({ input: process.stdin })
for await (const line of rl) {
  if (!line.trim()) continue
  const row = JSON.parse(line)
  const speakers = [...new Set(row.labels.map((l) => l.src))].filter((d) => d !== BSKY_LABELER_DID).slice(0, 20)
  const out = { subject: row.subject, kind: row.subject.startsWith('did:') ? 'account' : 'post' }
  for (const [name, lens] of Object.entries(lenses)) out[name] = judge(row, lens)
  out.all = judge(row, { userDid: VIEWER_DID, labelers: speakers })
  // Posts as judged on their own labels only, without the author's account labels that clients also apply.
  if (out.kind === 'post') {
    const own = { ...row, labels: row.labels.filter((l) => l.uri === row.subject) }
    for (const name of ['public', 'popular', 'protective']) out[`${name}_postonly`] = judge(own, lenses[name])
  }
  process.stdout.write(JSON.stringify(out) + '\n')
}
