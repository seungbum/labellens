"""Build the labeler directory shipped with the web app (web/public/labelers.json)."""
import json, sys

PROTECTIVE_GLOBALS = {"!hide", "!warn", "porn", "sexual", "nudity", "graphic-media"}


def category(rec):
    vals = set(rec.get("label_values") or [])
    defs = rec.get("definitions") or []
    if vals & PROTECTIVE_GLOBALS:
        return "protective"
    for d in defs:
        if d.get("blurs") in ("content", "media") or d.get("severity") == "alert" \
                or d.get("defaultSetting") == "hide":
            return "protective"
    return "descriptive" if vals else "undeclared"


def main(src, out, probe_path=None):
    probe = {}
    if probe_path:
        probe = {json.loads(l)["did"]: json.loads(l) for l in open(probe_path)}
    rows = []
    for line in open(src):
        r = json.loads(line)
        if not r.get("endpoint"):
            continue
        rows.append({"did": r["did"], "handle": r.get("handle"), "name": r.get("name"),
                     "endpoint": r["endpoint"].rstrip("/"), "likes": r.get("likes") or 0,
                     "category": category(r), "nvalues": len(r.get("label_values") or []),
                     "browser": bool(probe.get(r["did"], {}).get("cors")) if probe else None,
                     "live": (probe.get(r["did"], {}).get("status") == 200) if probe else None})
    rows.sort(key=lambda r: -r["likes"])
    json.dump({"generated": __import__("time").strftime("%Y-%m-%d"), "labelers": rows},
              open(out, "w"), separators=(",", ":"))
    print(len(rows), "labelers ->", out)


if __name__ == "__main__":
    main(*sys.argv[1:4])
