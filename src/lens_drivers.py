"""Which protective-stack labelers cause the posts whose presentation differs from the logged-out view.

Writes per-labeler counts only (no subjects), so the output is kept after the sample is deleted.
Usage: python src/lens_drivers.py data/lens_sample data/labelers.jsonl data/lens_drivers.json
"""
import collections, json, os, sys


def main(sample_dir, labelers_path, out_path):
    stacks = json.load(open(os.path.join(sample_dir, "stacks.json")))
    prot = set(stacks["protective"])
    handle = {json.loads(l)["did"]: json.loads(l).get("handle") for l in open(labelers_path)}
    verdicts = {}
    for line in open(os.path.join(sample_dir, "verdicts.jsonl")):
        r = json.loads(line)
        verdicts[r["subject"]] = r
    by = collections.Counter()
    n = 0
    for line in open(os.path.join(sample_dir, "sample.jsonl")):
        r = json.loads(line)
        v = verdicts[r["subject"]]
        if v["kind"] != "post" or v["public"] == v["protective"]:
            continue
        n += 1
        by.update({l["src"] for l in r["labels"] if l["src"] in prot})
    top, top_n = by.most_common(1)[0]
    out = {"n": n, "top": handle.get(top) or top, "top_did": top, "top_n": top_n,
           "top_index": stacks["protective"].index(top),
           "by_labeler": {handle.get(d) or d: c for d, c in by.most_common()}}
    json.dump(out, open(out_path, "w"), indent=1)
    print(out["n"], out["top"], out["top_n"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
