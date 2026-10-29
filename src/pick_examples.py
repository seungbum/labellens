"""List widely labelled public accounts as candidate examples for the demo.

Prints accounts labelled by the most services, with follower counts from the
public AppView, so a human can pick public organisational or official accounts.
"""
import collections, glob, gzip, json, os, sys
import requests


def main(label_dir, min_sources=4, top=300):
    srcs = collections.defaultdict(set)
    for path in glob.glob(os.path.join(label_dir, "*.jsonl.gz")):
        try:
            for line in gzip.open(path, "rt"):
                l = json.loads(line)
                if l.get("neg"):
                    continue
                u = l["uri"]
                if u.startswith("did:"):
                    srcs[u].add(l["src"])
        except (EOFError, OSError):
            pass  # file still being written
    acc = sorted((d for d, s in srcs.items() if len(s) >= min_sources), key=lambda d: -len(srcs[d]))[:top]
    out = []
    for i in range(0, len(acc), 25):
        r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles",
                         params={"actors": acc[i:i + 25]}, timeout=30).json()
        for p in r.get("profiles", []):
            out.append((p.get("followersCount", 0), len(srcs[p["did"]]), p["handle"], (p.get("displayName") or "")[:40]))
    for row in sorted(out, reverse=True)[:60]:
        print(*row, sep="\t")


if __name__ == "__main__":
    main(sys.argv[1])
