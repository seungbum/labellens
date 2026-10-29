"""Refuse a snapshot directory that is not restricted to an explicit list of subjects.

The published site may only carry labels about the example accounts in
data/snapshot_subjects.txt. A snapshot passes when its index.json has a non-empty
"subjects" list and every shard holds only those subjects.
Usage: python3 tests/check_snapshot.py docs/snapshot [more dirs]; exits 1 on failure.
"""
import glob, json, os, sys


def check(snap_dir):
    idx_path = os.path.join(snap_dir, "index.json")
    if not os.path.exists(idx_path):
        return None  # no snapshot at all is fine
    subjects = json.load(open(idx_path)).get("subjects")
    if not isinstance(subjects, list) or not subjects:
        return "index.json has no subjects list"
    allowed = set(subjects)
    for path in glob.glob(os.path.join(snap_dir, "*.json")):
        if os.path.basename(path) == "index.json":
            continue
        extra = set(json.load(open(path))) - allowed
        if extra:
            return f"{os.path.basename(path)} holds {len(extra)} subject(s) outside the subjects list"
    return None


def main(dirs):
    bad = 0
    for d in dirs:
        err = check(d)
        if err:
            print(f"refusing snapshot {d}: {err}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["docs/snapshot"]))
