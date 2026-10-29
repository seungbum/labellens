"""Append a log line for every labeler with an endpoint that the collector never finished.

Run after src/collect.py, also when it was stopped by a time limit, so that every
labeler with an endpoint has exactly one line with a stop_reason.
Usage: python src/mark_missing.py data/labelers.jsonl data/collect_log.jsonl
"""
import json, os, sys, time


def main(labelers_path, log_path):
    rows = {}
    if os.path.exists(log_path):
        for line in open(log_path):
            r = json.loads(line)
            rows[r["did"]] = r
    added = 0
    for line in open(labelers_path):
        rec = json.loads(line)
        if rec.get("endpoint") and rec["did"] not in rows:
            rows[rec["did"]] = {"did": rec["did"], "endpoint": rec["endpoint"], "n": 0,
                                "stop_reason": "time_limit", "complete": False, "complete_known": False,
                                "error": None, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            added += 1
    with open(log_path + ".tmp", "w") as f:
        for r in rows.values():
            f.write(json.dumps(r) + "\n")
    os.replace(log_path + ".tmp", log_path)
    print(f"{added} labelers marked as not collected; {len(rows)} log lines")


if __name__ == "__main__":
    main(*sys.argv[1:3])
