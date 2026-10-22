"""Collect label histories from every resolvable labeler.

Labelers whose current sequence number is above MAX_FULL are collected from
(latest - MAX_FULL) onward, i.e. a recent window; all others from seq 0.
Output: data/labels/<did>.jsonl.gz plus data/collect_log.jsonl.
"""
import asyncio, gzip, io, json, os, sys, time
import cbor2, websockets

MAX_FULL = int(os.environ.get("MAX_FULL", 3_000_000))
PROBE_SECONDS = 45
IDLE_SECONDS = 25
PARALLEL = int(os.environ.get("PARALLEL", 12))
UA = "labellens-research/0.1 (academic measurement; contact via github.com/seungbum)"


def wss(endpoint, cursor=None):
    u = endpoint.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    u += "/xrpc/com.atproto.label.subscribeLabels"
    return u + (f"?cursor={cursor}" if cursor is not None else "")


def decode(msg):
    buf = io.BytesIO(msg)
    return cbor2.load(buf), cbor2.load(buf)


async def probe_latest(endpoint):
    """Return the seq of the first live frame, or None if the labeler is quiet."""
    try:
        async with websockets.connect(wss(endpoint), max_size=None, open_timeout=20,
                                      user_agent_header=UA) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=PROBE_SECONDS)
            head, body = decode(msg)
            return body.get("seq")
    except Exception:
        return None


async def download(rec, outdir):
    did, ep = rec["did"], rec["endpoint"]
    t0 = time.time()
    latest = await probe_latest(ep)
    start = 0 if latest is None or latest <= MAX_FULL else latest - MAX_FULL
    n, last_seq, err, info = 0, None, None, []
    path = os.path.join(outdir, did.replace(":", "_") + ".jsonl.gz")
    with gzip.open(path, "wt") as f:
        try:
            async with websockets.connect(wss(ep, start), max_size=None, open_timeout=20,
                                          ping_interval=60, ping_timeout=120,
                                          user_agent_header=UA) as ws:
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_SECONDS)
                    except asyncio.TimeoutError:
                        break
                    head, body = decode(msg)
                    if head.get("t") != "#labels":
                        info.append({"head": head, "body": str(body)[:300]})
                        if head.get("op") == -1:
                            break
                        continue
                    last_seq = body.get("seq")
                    for lab in body.get("labels", []):
                        row = {k: lab.get(k) for k in ("src", "uri", "val", "neg", "cts", "exp")
                               if lab.get(k) is not None}
                        if lab.get("cid"):
                            row["cid"] = 1  # label pinned to a specific record version
                        row["seq"] = last_seq
                        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
                        n += 1
                    if latest is not None and last_seq is not None and last_seq >= latest:
                        break  # caught up with the probe point; stop before the live tail
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
    return {"did": did, "endpoint": ep, "latest_probe": latest, "start": start, "n": n,
            "last_seq": last_seq, "error": err, "info": info[:3],
            "seconds": round(time.time() - t0, 1), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


async def main(labelers_path, outdir, log_path):
    os.makedirs(outdir, exist_ok=True)
    done = set()
    if os.path.exists(log_path):
        done = {json.loads(l)["did"] for l in open(log_path)}
    recs = [json.loads(l) for l in open(labelers_path)]
    recs = [r for r in recs if r.get("endpoint") and r["did"] not in done]
    sem = asyncio.Semaphore(PARALLEL)
    log = open(log_path, "a")

    async def one(r):
        async with sem:
            res = await download(r, outdir)
            log.write(json.dumps(res) + "\n"); log.flush()
            print(res["did"], res["n"], res["error"], res["seconds"], flush=True)

    await asyncio.gather(*(one(r) for r in recs))


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
