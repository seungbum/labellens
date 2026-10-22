"""Build the static label snapshot used for labelers a browser cannot query.

Some labeler services answer queryLabels but send no CORS header, so a web page
cannot read them. For those, the web app falls back to the labels in force at
collection time, sharded by the subject's DID.

With a subjects file (one DID per line, # starts a comment), only labels about those
accounts and their posts are kept. The published site uses data/snapshot_subjects.txt,
the organisational example accounts, so it does not republish labels about individual
people; leave the file out for a full snapshot that stays on your own machine.

Usage: python src/build_snapshot.py data/labelers.jsonl data/probe_X.jsonl data/collect_log.jsonl data/labels web/public/snapshot [subjects.txt]
"""
import collections, datetime as dt, gzip, hashlib, json, os, shutil, sys

SHARD_CHARS = 3  # 4096 shards


def shard_of(did):
    return hashlib.sha1(did.encode()).hexdigest()[:SHARD_CHARS]


def subject_did(uri):
    if uri.startswith("did:"):
        return uri
    if uri.startswith("at://"):
        return uri[5:].split("/", 1)[0]
    return None


def read_subjects(path):
    if not path:
        return None
    return {line.split("#", 1)[0].strip() for line in open(path)} - {""}


def main(labelers_path, probe_path, log_path, label_dir, out_dir, subjects_path=None):
    subjects = read_subjects(subjects_path)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    probe = {json.loads(l)["did"]: json.loads(l) for l in open(probe_path)}
    logs = {json.loads(l)["did"]: json.loads(l) for l in open(log_path)}
    browser_ok = {d for d, p in probe.items() if p.get("status") == 200 and p.get("json") and p.get("cors")}
    sources = [d for d, lg in logs.items() if lg["n"] and d not in browser_ok]
    src_index = {d: i for i, d in enumerate(sources)}
    shards = collections.defaultdict(lambda: collections.defaultdict(list))
    kept = 0
    for did in sources:
        latest = {}
        for line in gzip.open(os.path.join(label_dir, did.replace(":", "_") + ".jsonl.gz"), "rt"):
            l = json.loads(line)
            if l.get("src") != did:
                continue
            k = (l["uri"], l["val"])
            if k not in latest or (l.get("cts") or "") >= (latest[k].get("cts") or ""):
                latest[k] = l
        for (uri, val), l in latest.items():
            if l.get("neg") or (l.get("exp") and l["exp"] < now):
                continue
            sd = subject_did(uri)
            if not sd or (subjects is not None and sd not in subjects):
                continue
            rest = uri[len(f"at://{sd}"):] if uri.startswith("at://") else ""
            shards[shard_of(sd)][sd].append([src_index[did], rest, val, l.get("cts")])
            kept += 1
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    for key, subjects in shards.items():
        with open(os.path.join(out_dir, f"{key}.json"), "w") as f:
            json.dump(subjects, f, separators=(",", ":"))
    json.dump({"generated": now, "sources": sources, "shard_chars": SHARD_CHARS, "labels": kept,
               "subjects": sorted(subjects) if subjects is not None else None},
              open(os.path.join(out_dir, "index.json"), "w"), separators=(",", ":"))
    print(f"{kept} labels in force from {len(sources)} services -> {len(shards)} shards in {out_dir}")


if __name__ == "__main__":
    main(*sys.argv[1:7])
