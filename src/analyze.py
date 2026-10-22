"""Summarise collected label logs into per-labeler and network statistics.

Usage: python src/analyze.py data/labelers.jsonl data/collect_log.jsonl data/labels out.json
"""
import collections, datetime as dt, gzip, json, os, statistics, sys

GLOBAL_VALUES = {"!hide", "!warn", "!no-unauthenticated", "!no-promote", "porn", "sexual",
                 "nudity", "graphic-media", "gore"}
B32 = "234567abcdefghijklmnopqrstuvwxyz"


def tid_time(rkey):
    """Creation time encoded in a TID record key, or None if the key is not a TID."""
    if len(rkey) != 13 or any(c not in B32 for c in rkey):
        return None
    n = 0
    for c in rkey:
        n = n * 32 + B32.index(c)
    us = n >> 10
    try:
        return dt.datetime.fromtimestamp(us / 1e6, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def target_kind(uri):
    if uri.startswith("did:"):
        return "account"
    if "/app.bsky.actor.profile/" in uri:
        return "profile"
    if "/app.bsky.feed.post/" in uri:
        return "post"
    if uri.startswith("at://"):
        return "other-record"
    return "non-atproto"


def summarise(rec, path, now):
    declared = set(rec.get("label_values") or [])
    latest = {}
    n = neg = expiring = inert = 0
    kinds = collections.Counter()
    first = last = None
    latencies = []
    for line in gzip.open(path, "rt"):
        l = json.loads(line)
        if l.get("src") != rec["did"]:
            continue  # a shared service replays other labelers' labels too; count them there
        n += 1
        if l.get("neg"):
            neg += 1
        if l.get("exp"):
            expiring += 1
        if l["val"] not in declared and l["val"] not in GLOBAL_VALUES:
            inert += 1
        kinds[target_kind(l["uri"])] += 1
        cts = l.get("cts")
        if cts:
            first = cts if first is None or cts < first else first
            last = cts if last is None or cts > last else last
        if not l.get("neg") and "/app.bsky.feed.post/" in l["uri"] and len(latencies) < 200000:
            made, labelled = tid_time(l["uri"].rsplit("/", 1)[-1]), parse_ts(cts or "")
            if made and labelled:
                latencies.append((labelled - made).total_seconds())
        # Fold to the latest label per (subject, value). Keys are 64-bit hashes and only
        # account subjects keep their URI: the largest services emit tens of millions of labels.
        uri, val = l["uri"], sys.intern(l["val"])
        k = hash((uri, val))
        prev = latest.get(k)
        if prev is None or (cts or "") >= prev[0]:
            latest[k] = (cts or "", bool(l.get("neg")), l.get("exp"), val,
                         uri if uri.startswith("did:") else hash(uri))
    active = [v for v in latest.values() if not v[1] and not (v[2] and v[2] < now)]
    subjects = {v[4] for v in active}
    lat = sorted(x for x in latencies if x >= 0)
    q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None
    return {
        "labels": n, "negations": neg, "expiring": expiring, "inert": inert,
        "active": len(active), "active_subjects": len(subjects),
        "retracted_pairs": sum(1 for v in latest.values() if v[1]),
        "kinds": dict(kinds), "first": first, "last": last,
        "latency_s": {"n": len(lat), "p50": q(.5), "p90": q(.9)},
        "top_values": collections.Counter(v[3] for v in active).most_common(8),
    }, subjects


def main(labelers_path, log_path, label_dir, out_path):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recs = {json.loads(l)["did"]: json.loads(l) for l in open(labelers_path)}
    logs = {json.loads(l)["did"]: json.loads(l) for l in open(log_path)}
    sys.path.insert(0, os.path.dirname(__file__))
    from build_labelers import category
    per, subject_sets = {}, {}
    for did, log in logs.items():
        path = os.path.join(label_dir, did.replace(":", "_") + ".jsonl.gz")
        if not log["n"] or not os.path.exists(path):
            continue
        stats, subjects = summarise(recs[did], path, now)
        stats.update(handle=recs[did].get("handle"), category=category(recs[did]),
                     windowed=bool(log.get("start")), likes=recs[did].get("likes") or 0)
        per[did] = stats
        if stats["category"] == "protective":
            subject_sets[did] = {s for s in subjects if isinstance(s, str)}
    # Co-labelling: for each protective labeler, how many of its labelled accounts
    # does at least one other protective labeler also label?
    owners = collections.Counter()
    for s in subject_sets.values():
        owners.update(s)
    for did, s in subject_sets.items():
        per[did]["accounts"] = len(s)
        per[did]["accounts_colabelled"] = sum(1 for x in s if owners[x] > 1)
    out = {"generated": now, "labelers_total": len(recs), "collected": len(per), "per_labeler": per,
           "accounts_by_protective_labelers": len(owners),
           "accounts_with_2plus_protective": sum(1 for v in owners.values() if v > 1)}
    json.dump(out, open(out_path, "w"), indent=1)
    print(f"{len(per)} labelers summarised -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
