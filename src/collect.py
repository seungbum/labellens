"""Collect label histories from every resolvable labeler.

Labelers whose current sequence number is above MAX_FULL are collected from
(latest - MAX_FULL) onward, i.e. a recent window; all others from seq 0. Services
whose sequence numbers are millisecond timestamps are always replayed from 0, since
a window of MAX_FULL "sequence numbers" would cover under an hour.

A stream that stops before reaching the probed head (idle timeout or a closed
connection) is resumed from the last stored seq, up to MAX_RECONNECT times. Each log
line records why the download stopped and whether it is known to be complete.
Output: data/labels/<did>.jsonl.gz plus data/collect_log.jsonl (one line per labeler).
"""
import asyncio, gzip, io, json, os, sys, time
import cbor2, websockets

sys.path.insert(0, os.path.dirname(__file__))
from list_labelers import endpoint_class

MAX_FULL = int(os.environ.get("MAX_FULL", 3_000_000))
MAX_RECONNECT = int(os.environ.get("MAX_RECONNECT", 20))
PROBE_SECONDS = 45
IDLE_SECONDS = int(os.environ.get("IDLE_SECONDS", 25))
PARALLEL = int(os.environ.get("PARALLEL", 12))
TIMESTAMP_SEQ = 10 ** 12  # larger sequence numbers are millisecond timestamps
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
            if isinstance(msg, str):
                return None
            head, body = decode(msg)
            return body.get("seq")
    except Exception:
        return None


def window(latest):
    """Start cursor and window kind for a probed head."""
    if latest is None:
        return 0, "full"
    if latest >= TIMESTAMP_SEQ:
        return 0, "timestamp"
    if latest <= MAX_FULL:
        return 0, "full"
    return latest - MAX_FULL, "seq"


async def download(rec, outdir):
    did, ep = rec["did"], rec["endpoint"]
    t0 = time.time()
    latest = await probe_latest(ep)
    start, window_kind = window(latest)
    n, last_seq, err, info, reconnects, stop_reason = 0, None, None, [], 0, None
    path = os.path.join(outdir, did.replace(":", "_") + ".jsonl.gz")
    with gzip.open(path, "wt") as f:
        cursor = start
        while True:
            progressed = False
            try:
                async with websockets.connect(wss(ep, cursor), max_size=None, open_timeout=20,
                                              ping_interval=60, ping_timeout=120,
                                              user_agent_header=UA) as ws:
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_SECONDS)
                        except asyncio.TimeoutError:
                            stop_reason = "idle"
                            break
                        if isinstance(msg, str):
                            info.append({"text_frame": msg[:300]})
                            continue
                        head, body = decode(msg)
                        if head.get("t") != "#labels":
                            info.append({"head": head, "body": str(body)[:300]})
                            if head.get("op") == -1:
                                stop_reason = "error_frame"
                                break
                            continue
                        seq = body.get("seq")
                        if seq is not None and last_seq is not None and seq <= last_seq:
                            continue  # replayed again after a reconnect
                        last_seq = seq
                        progressed = True
                        for lab in body.get("labels", []):
                            row = {k: lab.get(k) for k in ("src", "uri", "val", "neg", "cts", "exp")
                                   if lab.get(k) is not None}
                            if lab.get("cid"):
                                row["cid"] = 1  # label pinned to a specific record version
                            row["seq"] = seq
                            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
                            n += 1
                        if latest is not None and last_seq is not None and last_seq >= latest:
                            stop_reason = "caught_up"
                            break
            except websockets.ConnectionClosed:
                stop_reason = "closed"
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                stop_reason = "error"
            if stop_reason in ("caught_up", "error_frame") or err:
                break
            # Stopped early (idle or closed). A quiet labeler (no probed head) also gets
            # one more connection after any progress, which exposes per-connection caps.
            if not progressed or reconnects >= MAX_RECONNECT or last_seq is None:
                break
            reconnects += 1
            cursor = last_seq  # the server sends events after the cursor
    complete = latest is not None and last_seq is not None and last_seq >= latest
    return {"did": did, "endpoint": ep, "latest_probe": latest, "start": start,
            "window_kind": window_kind, "n": n, "last_seq": last_seq, "error": err,
            "stop_reason": stop_reason, "complete": complete, "complete_known": latest is not None,
            "reconnects": reconnects, "info": info[:3], "seconds": round(time.time() - t0, 1),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def dedupe_log(log_path):
    """Keep one line per labeler (the last), so a resumed run never double-counts."""
    rows = {}
    for line in open(log_path):
        r = json.loads(line)
        rows[r["did"]] = r
    with open(log_path + ".tmp", "w") as f:
        for r in rows.values():
            f.write(json.dumps(r) + "\n")
    os.replace(log_path + ".tmp", log_path)


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
            kind = endpoint_class(r["endpoint"])
            base = {"did": r["did"], "endpoint": r["endpoint"], "n": 0, "complete": False,
                    "complete_known": False, "seconds": 0}
            try:
                if kind in ("valid", "non_https"):
                    res = await download(r, outdir)
                else:  # a broken declaration (localhost, a web page, no scheme): nothing to connect to
                    res = dict(base, error=None, stop_reason="invalid_endpoint", endpoint_class=kind)
            except Exception as e:  # never let one labeler stop the whole run
                res = dict(base, error=f"collector: {type(e).__name__}: {str(e)[:200]}", stop_reason="error")
            res.setdefault("finished_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            log.write(json.dumps(res) + "\n"); log.flush()
            print(res["did"], res["n"], res["stop_reason"], res["complete"], res["error"], res["seconds"], flush=True)

    await asyncio.gather(*(one(r) for r in recs))
    log.close()
    dedupe_log(log_path)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
