"""Assemble web/public/network.json from the measurement outputs.

Usage: python src/build_network.py data/labelers.jsonl data/probe_X.jsonl data/network_raw.json data/lens_sample/verdicts.jsonl out.json
"""
import collections, json, sys


def lens_summary(path):
    rows = [json.loads(l) for l in open(path)]
    out = {}
    for kind in ("account", "post"):
        s = [r for r in rows if r["kind"] == kind]
        if not s:
            continue
        lenses = [k for k in s[0] if k not in ("subject", "kind")]
        out[kind] = {"n": len(s),
                     "outcomes": {k: dict(collections.Counter(r[k] for r in s)) for k in lenses},
                     "differs_from_public": {k: sum(r[k] != r["public"] for r in s) for k in lenses if k != "public"}}
    return out


def main(labelers_path, probe_path, raw_path, verdicts_path, out_path):
    recs = [json.loads(l) for l in open(labelers_path)]
    probe = {json.loads(l)["did"]: json.loads(l) for l in open(probe_path)}
    raw = json.load(open(raw_path))
    answering = {d for d, p in probe.items() if p.get("status") == 200 and p.get("json")}
    browser = {d for d in answering if probe[d].get("cors")}
    per = {}
    for did, r in raw["per_labeler"].items():
        if not r["labels"]:
            continue
        r = dict(r, browser=did in browser, answering=did in answering)
        r.pop("top_values", None)  # values can name individuals' traits; keep the page aggregate
        per[did] = r
    summary = {
        "declared": len(recs),
        "resolvable": sum(1 for r in recs if r.get("endpoint")),
        "answering": len(answering),
        "browser": len(browser),
        "collected": len(per),
        "labels": sum(r["labels"] for r in per.values()),
        "inert": sum(r["inert"] for r in per.values()),
        "active": sum(r["active"] for r in per.values()),
        "retracted_pairs": sum(r["retracted_pairs"] for r in per.values()),
        "accounts_by_protective": raw["accounts_by_protective_labelers"],
        "accounts_2plus_protective": raw["accounts_with_2plus_protective"],
    }
    out = {"generated": raw["generated"], "summary": summary, "lenses": lens_summary(verdicts_path),
           "per_labeler": per}
    json.dump(out, open(out_path, "w"), separators=(",", ":"))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:6])
