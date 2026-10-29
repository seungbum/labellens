"""Collect one large labeler's stream over several parallel connections.

A single subscribeLabels connection can be slow for the largest services (one took
hours from a cloud workspace). This script finds the stream head by probing cursors
(a cursor past the head gets a FutureCursor error), splits [0, head] into PARTS ranges,
replays them in parallel (each range resumes after a stop, like collect.py), and writes
the labels in sequence order to data/labels/<did>.jsonl.gz. The labeler's line in the
collection log is replaced.
Usage: python src/collect_split.py data/labelers.jsonl data/labels data/collect_log.jsonl DID [PARTS]
"""
import asyncio, gzip, json, os, sys, time
import websockets

sys.path.insert(0, os.path.dirname(__file__))
from collect import UA, decode, wss

MAX_RECONNECT = 50
IDLE_SECONDS = 30


async def first_frame(ep, cursor):
    """'labels' if events exist after cursor, 'future' if the cursor is past the head, else None."""
    try:
        async with websockets.connect(wss(ep, cursor), max_size=None, open_timeout=20, user_agent_header=UA) as ws:
            head, body = decode(await asyncio.wait_for(ws.recv(), timeout=20))
            if head.get("t") == "#labels":
                return "labels"
            return "future" if body.get("error") == "FutureCursor" else None
    except Exception:
        return None


async def find_head(ep):
    lo, hi = 0, 1
    while await first_frame(ep, hi) == "labels":
        lo, hi = hi, hi * 2
    while hi - lo > 1000:  # events exist after lo; none (or a future cursor) at hi
        mid = (lo + hi) // 2
        if await first_frame(ep, mid) == "labels":
            lo = mid
        else:
            hi = mid
    return lo, hi


async def part(ep, a, b, path, tail_after=None):
    """Replay events with a < seq <= b into path; return (n, last_seq, reconnects, done).
    The last range ends at the head, whose exact seq is unknown: it is done when the
    stream goes idle after passing tail_after (a seq known to have later events)."""
    n, last, reconnects, failures = 0, a, 0, 0
    with gzip.open(path, "wt") as f:
        while last < b and failures <= MAX_RECONNECT:
            progressed = False
            try:
                async with websockets.connect(wss(ep, last), max_size=None, open_timeout=20, ping_interval=60,
                                              ping_timeout=120, user_agent_header=UA) as ws:
                    while last < b:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_SECONDS)
                        except asyncio.TimeoutError:
                            if tail_after is not None and last > tail_after:
                                return n, last, reconnects, True
                            raise
                        if isinstance(msg, str):
                            continue
                        head, body = decode(msg)
                        seq = body.get("seq")
                        if head.get("t") != "#labels" or seq is None or seq <= last:
                            continue
                        if seq > b:
                            last = b
                            break
                        for lab in body.get("labels", []):
                            row = {k: lab.get(k) for k in ("src", "uri", "val", "neg", "cts", "exp") if lab.get(k) is not None}
                            if lab.get("cid"):
                                row["cid"] = 1
                            row["seq"] = seq
                            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
                            n += 1
                        last, progressed = seq, True
            except Exception:
                pass
            if last < b:
                reconnects += 1
                if not progressed:  # some servers close every connection after a few hundred events
                    failures += 1
                    await asyncio.sleep(5)
    return n, last, reconnects, last >= b


async def main(labelers_path, outdir, log_path, did, parts=10):
    parts = int(parts)
    rec = next(json.loads(l) for l in open(labelers_path) if json.loads(l)["did"] == did)
    ep, t0 = rec["endpoint"], time.time()
    lo, head = await find_head(ep)
    print("head between", lo, head, flush=True)
    bounds = [round(head * i / parts) for i in range(parts + 1)]
    base = os.path.join(outdir, did.replace(":", "_"))
    # The last range runs on to the live head, which keeps moving while the others replay.
    res = await asyncio.gather(*(part(ep, bounds[i], bounds[i + 1] if i < parts - 1 else float("inf"),
                                      f"{base}.part{i}.gz", tail_after=lo if i == parts - 1 else None)
                                 for i in range(parts)))
    with gzip.open(base + ".jsonl.gz", "wt") as out:
        for i in range(parts):
            with gzip.open(f"{base}.part{i}.gz", "rt") as f:
                for line in f:
                    out.write(line)
            os.remove(f"{base}.part{i}.gz")
    complete = all(r[3] for r in res)
    line = {"did": did, "endpoint": ep, "latest_probe": head, "start": 0, "window_kind": "full",
            "n": sum(r[0] for r in res), "last_seq": max(r[1] for r in res), "error": None,
            "stop_reason": "caught_up" if complete else "idle", "complete": complete, "complete_known": True,
            "reconnects": sum(r[2] for r in res), "parts": parts, "info": [],
            "seconds": round(time.time() - t0, 1), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rows = [json.loads(l) for l in open(log_path) if json.loads(l)["did"] != did] if os.path.exists(log_path) else []
    with open(log_path + ".tmp", "w") as f:
        for r in rows + [line]:
            f.write(json.dumps(r) + "\n")
    os.replace(log_path + ".tmp", log_path)
    print(json.dumps(line), flush=True)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:6]))
