// Label folding shared by the site and tests/test_regressions.py.

// Fold a labeler's raw label log into the labels in force now.
export function activeLabels(raw, now = Date.now()) {
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

// Expand one subject's snapshot rows ([source index, uri suffix, val, cts, exp]) into labels.
export function snapshotLabels(rows, did, uris, sources) {
  const out = []
  for (const [i, rest, val, cts, exp] of rows || []) {
    const uri = rest ? `at://${did}${rest}` : did
    if (!uris.includes(uri)) continue
    out.push({ src: sources[i], uri, val, cts, ...(exp ? { exp } : {}) })
  }
  return out
}
