"""Download a labeler's full label history via com.atproto.label.subscribeLabels."""
import asyncio, io, json, sys, time
import cbor2, websockets


async def dump(endpoint, out, max_seconds=600, idle=20):
    url = endpoint.replace("https://", "wss://").rstrip("/") + "/xrpc/com.atproto.label.subscribeLabels?cursor=0"
    n, last_seq, t0 = 0, None, time.time()
    with open(out, "w") as f:
        try:
            async with websockets.connect(url, max_size=None, open_timeout=20,
                                          user_agent_header="labellens-research/0.1") as ws:
                while time.time() - t0 < max_seconds:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=idle)
                    except asyncio.TimeoutError:
                        break  # caught up with the live tail
                    buf = io.BytesIO(msg)
                    head = cbor2.load(buf)
                    body = cbor2.load(buf)
                    if head.get("t") != "#labels":
                        f.write(json.dumps({"frame": head, "body": str(body)[:500]}) + "\n")
                        continue
                    last_seq = body.get("seq")
                    for lab in body.get("labels", []):
                        lab.pop("sig", None)
                        if "cid" in lab and not isinstance(lab["cid"], str):
                            lab["cid"] = str(lab["cid"])
                        lab["seq"] = last_seq
                        f.write(json.dumps(lab, default=str) + "\n")
                        n += 1
        except Exception as e:
            print("error", endpoint, type(e).__name__, str(e)[:200], file=sys.stderr)
    return n, last_seq, time.time() - t0


if __name__ == "__main__":
    print(asyncio.run(dump(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 600)))
