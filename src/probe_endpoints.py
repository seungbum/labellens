"""Probe every labeler endpoint once: does queryLabels answer, and may a browser read it (CORS)?"""
import concurrent.futures as cf, json, sys, time
import requests

SUBJECT = "did:plc:z72i7hdynmk6r22z27h6tvur"  # bsky.app, a public organisational account
ORIGIN = "https://seungbum.github.io"


def probe(rec):
    url = rec["endpoint"].rstrip("/") + "/xrpc/com.atproto.label.queryLabels"
    out = {"did": rec["did"], "endpoint": rec["endpoint"]}
    t0 = time.time()
    try:
        r = requests.get(url, params={"uriPatterns": SUBJECT}, headers={"Origin": ORIGIN,
                         "User-Agent": "labellens-research/0.1"}, timeout=10)
        out.update(status=r.status_code, cors=r.headers.get("access-control-allow-origin"),
                   ms=round(1000 * (time.time() - t0)))
        try:
            out["json"] = isinstance(r.json().get("labels"), list)
        except Exception:
            out["json"] = False
    except requests.RequestException as e:
        out.update(status=None, error=type(e).__name__, ms=round(1000 * (time.time() - t0)))
    return out


def main(src, dst):
    recs = [json.loads(l) for l in open(src) if json.loads(l).get("endpoint")]
    with cf.ThreadPoolExecutor(32) as ex, open(dst, "w") as f:
        for res in ex.map(probe, recs):
            res["probed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            f.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
