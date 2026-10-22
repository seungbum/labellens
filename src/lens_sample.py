"""Draw a hash-based sample of labelled subjects and write their labels in force.

A subject (account DID or post URI) is sampled when md5(subject) mod RATE == 0, so the
sample is uniform over every subject any collected labeler has labelled, and one pass
collects all labels on each sampled subject. Profile-record labels count towards the
account. Output feeds web/src/lens_eval.mjs.

Usage: python src/lens_sample.py data/labels data/labelers.jsonl RATE out_dir
"""
import collections, datetime as dt, glob, gzip, hashlib, json, os, sys


def subject_of(uri):
    if uri.startswith("did:"):
        return uri, uri
    if uri.startswith("at://"):
        did = uri[5:].split("/", 1)[0]
        if uri.endswith("/app.bsky.actor.profile/self"):
            return did, did
        if "/app.bsky.feed.post/" in uri:
            return uri, did
    return None, None


def main(label_dir, labelers_path, rate, out_dir):
    rate = int(rate)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    latest = {}
    for path in sorted(glob.glob(os.path.join(label_dir, "*.jsonl.gz"))):
        for line in gzip.open(path, "rt"):
            l = json.loads(line)
            subj, did = subject_of(l["uri"])
            if subj is None or int(hashlib.md5(subj.encode()).hexdigest()[:8], 16) % rate:
                continue
            k = (l["src"], l["uri"], l["val"])
            if k not in latest or (l.get("cts") or "") >= (latest[k].get("cts") or ""):
                latest[k] = dict(l, subject=subj, did=did)
    rows = collections.defaultdict(list)
    for l in latest.values():
        if l.get("neg") or (l.get("exp") and l["exp"] < now):
            continue
        rows[(l["subject"], l["did"])].append({k: l[k] for k in ("src", "uri", "val", "cts") if k in l})
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sample.jsonl"), "w") as f:
        for (subj, did), labels in rows.items():
            f.write(json.dumps({"subject": subj, "did": did, "labels": labels}) + "\n")
    # Labeler views in the shape interpretLabelValueDefinitions expects.
    views = {}
    for line in open(labelers_path):
        r = json.loads(line)
        views[r["did"]] = {"creator": {"did": r["did"]},
                           "policies": {"labelValues": r.get("label_values") or [],
                                        "labelValueDefinitions": r.get("definitions") or []}}
    json.dump(views, open(os.path.join(out_dir, "views.json"), "w"))
    sys.path.insert(0, os.path.dirname(__file__))
    from build_labelers import category
    recs = [json.loads(l) for l in open(labelers_path)]
    recs = [r for r in sorted(recs, key=lambda r: -(r.get("likes") or 0))
            if r.get("endpoint") and r["did"] != "did:plc:ar7c4by46qjdydhdevvrndac"]
    stacks = {"popular": [r["did"] for r in recs][:20],  # the web app's "Popular stack"
              "protective": [r["did"] for r in recs if category(r) == "protective"][:20]}
    json.dump(stacks, open(os.path.join(out_dir, "stacks.json"), "w"))
    print(f"{len(rows)} sampled subjects (1 in {rate}) -> {out_dir}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
