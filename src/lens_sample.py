"""Draw a hash-based sample of labelled subjects and write their labels in force.

A subject (account DID or post URI) is sampled when md5(subject) mod RATE == 0, so the
sample is uniform over every subject any collected labeler has labelled, and a pass over
all streams collects every label on each sampled subject. Profile-record labels count towards the
account. Only labels a service issued itself are kept (src equals the file's labeler), as
in the web app. A sampled post also carries its author's account labels, which clients
apply to posts. Authors' self-labels live in post records, not label streams, and are
not included. Output feeds web/src/lens_eval.mjs.

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


def owned_rows(label_dir, owners):
    """Yield (owner, label) for every label a service issued itself. Shared services also
    replay other labelers' labels; those are counted at the other labeler's own file, as
    the web app keeps only l.src === labeler for each service it asks."""
    for path in sorted(glob.glob(os.path.join(label_dir, "*.jsonl.gz"))):
        owner = owners.get(os.path.basename(path))
        for line in gzip.open(path, "rt"):
            l = json.loads(line)
            if owner and l.get("src") != owner:
                continue
            yield l


def fold(latest, l, **extra):
    k = (l["src"], l["uri"], l["val"])
    if k not in latest or (l.get("cts") or "") >= (latest[k].get("cts") or ""):
        latest[k] = dict(l, **extra)


def main(label_dir, labelers_path, rate, out_dir):
    rate = int(rate)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    owners = {json.loads(l)["did"].replace(":", "_") + ".jsonl.gz": json.loads(l)["did"]
              for l in open(labelers_path)}
    sampled = lambda subj: int(hashlib.md5(subj.encode()).hexdigest()[:8], 16) % rate == 0
    # Pass 1: labels on sampled subjects; remember the authors of sampled posts.
    latest, authors = {}, set()
    for l in owned_rows(label_dir, owners):
        subj, did = subject_of(l["uri"])
        if subj is None or not sampled(subj):
            continue
        fold(latest, l, subject=subj, did=did)
        if subj != did:
            authors.add(did)
    # Pass 2: account labels on those authors, which clients apply to their posts too.
    acct = {}
    for l in owned_rows(label_dir, owners):
        subj, did = subject_of(l["uri"])
        if subj is not None and subj == did and did in authors:
            fold(acct, l, subject=did, did=did)
    in_force = lambda l: not l.get("neg") and not (l.get("exp") and l["exp"] < now)
    keep = lambda l: {k: l[k] for k in ("src", "uri", "val", "cts", "exp") if k in l}
    acct_by_did = collections.defaultdict(list)
    for l in acct.values():
        if in_force(l):
            acct_by_did[l["did"]].append(keep(l))
    rows = collections.defaultdict(list)
    for l in latest.values():
        if in_force(l):
            rows[(l["subject"], l["did"])].append(keep(l))
    for (subj, did), labels in rows.items():
        if subj != did:
            labels.extend(acct_by_did.get(did, []))
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
    from list_labelers import endpoint_class
    recs = [json.loads(l) for l in open(labelers_path)]
    recs = [r for r in sorted(recs, key=lambda r: -(r.get("likes") or 0))
            if endpoint_class(r.get("endpoint")) == "valid" and r["did"] != "did:plc:ar7c4by46qjdydhdevvrndac"]
    prot_all = [r["did"] for r in recs if category(r) == "protective"]
    stacks = {"popular": [r["did"] for r in recs][:20],  # the web app's "Popular stack"
              "protective": prot_all[:20]}
    # Sensitivity of the protective lens to single services: leave one out, and swap one
    # for the 21st most-liked protective labeler (keeps the stack at the 20-labeler cap).
    for i, did in enumerate(prot_all[:20]):
        stacks[f"protective_minus_{i}"] = [d for d in prot_all[:20] if d != did]
        stacks[f"protective_swap_{i}"] = stacks[f"protective_minus_{i}"] + prot_all[20:21]
    json.dump(stacks, open(os.path.join(out_dir, "stacks.json"), "w"))
    print(f"{len(rows)} sampled subjects (1 in {rate}) -> {out_dir}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
