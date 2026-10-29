"""Regression tests for the snapshot guard, collection resume and snapshot expiry.

Run from the repository root: python tests/test_regressions.py (needs the Python
requirements and web/node_modules for the expiry test).
"""
import asyncio, gzip, io, json, os, subprocess, sys, tempfile

import cbor2

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "localhost,127.0.0.1"

ALICE, BOB, SRC = "did:plc:alice", "did:plc:bob", "did:plc:labeler"


def fake_run(tmp):
    """A labeler without CORS that labelled two accounts."""
    w = lambda name, rows: open(os.path.join(tmp, name), "w").write("".join(json.dumps(r) + "\n" for r in rows))
    w("labelers.jsonl", [{"did": SRC, "endpoint": "https://labeler.example"}])
    w("probe.jsonl", [{"did": SRC, "status": 200, "json": True, "cors": None}])
    w("log.jsonl", [{"did": SRC, "n": 2}])
    os.makedirs(os.path.join(tmp, "labels"))
    with gzip.open(os.path.join(tmp, "labels", SRC.replace(":", "_") + ".jsonl.gz"), "wt") as f:
        for did in (ALICE, BOB):
            f.write(json.dumps({"src": SRC, "uri": did, "val": "spam", "cts": "2026-10-01T00:00:00Z"}) + "\n")


def test_publish_guard():
    import build_snapshot, check_snapshot
    with tempfile.TemporaryDirectory() as tmp:
        fake_run(tmp)
        args = [os.path.join(tmp, x) for x in ("labelers.jsonl", "probe.jsonl", "log.jsonl", "labels")]
        build_snapshot.main(*args, os.path.join(tmp, "full"))
        assert check_snapshot.main([os.path.join(tmp, "full")]) == 1, "a full snapshot must be refused"
        open(os.path.join(tmp, "subjects.txt"), "w").write(ALICE + "  # example\n")
        build_snapshot.main(*args, os.path.join(tmp, "public"), os.path.join(tmp, "subjects.txt"))
        assert check_snapshot.main([os.path.join(tmp, "public")]) == 0, "a restricted snapshot must pass"
        idx = json.load(open(os.path.join(tmp, "public", "index.json")))
        assert idx["subjects"] == [ALICE] and idx["labels"] == 1
        # A shard that gained a foreign subject is refused even with a subjects list.
        shard = [p for p in os.listdir(os.path.join(tmp, "public")) if p != "index.json"][0]
        path = os.path.join(tmp, "public", shard)
        data = json.load(open(path)); data[BOB] = data[ALICE]; json.dump(data, open(path, "w"))
        assert check_snapshot.main([os.path.join(tmp, "public")]) == 1
    # build.sh runs the guard before and after publishing.
    assert open(os.path.join(ROOT, "web", "build.sh")).read().count("check_snapshot.py") == 2


def frame(seq):
    buf = io.BytesIO()
    cbor2.dump({"op": 1, "t": "#labels"}, buf)
    cbor2.dump({"seq": seq, "labels": [{"src": SRC, "uri": f"did:plc:s{seq}", "val": "spam",
                                        "cts": "2026-10-01T00:00:00Z"}]}, buf)
    return buf.getvalue()


async def resume_case():
    import websockets
    from websockets.asyncio.server import serve
    import collect
    collect.IDLE_SECONDS = 2
    collect.PROBE_SECONDS = 5
    head, per_conn = 1000, 300

    async def handler(ws):
        cursor = ws.request.path.partition("cursor=")[2]
        if not cursor:  # live tail only: the probe sees the head
            await ws.send(frame(head))
            await asyncio.sleep(10)
            return
        for seq in range(int(cursor) + 1, min(head, int(cursor) + per_conn) + 1):
            await ws.send(frame(seq))
        await ws.close()  # a server that ends every connection after a fixed backfill

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            res = await collect.download({"did": SRC, "endpoint": f"http://127.0.0.1:{port}"}, tmp)
            rows = [json.loads(l) for l in gzip.open(os.path.join(tmp, SRC.replace(":", "_") + ".jsonl.gz"), "rt")]
    return res, rows


def test_collect_resume():
    res, rows = asyncio.run(resume_case())
    assert res["complete"] and res["stop_reason"] == "caught_up", res
    assert res["reconnects"] >= 1, res
    assert [r["seq"] for r in rows] == list(range(1, 1001)), "every frame once, in order"


def test_snapshot_exp():
    js = """
      import { activeLabels, snapshotLabels } from './web/src/labels.js'
      const did = 'did:plc:alice', uris = [did]
      const rows = [[0, '', 'spam', '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z'],
                    [0, '', 'rude', '2026-01-01T00:00:00Z', null]]
      const labels = snapshotLabels(rows, did, uris, ['did:plc:labeler'])
      const r = activeLabels(labels, Date.parse('2026-10-28T00:00:00Z'))
      console.log(JSON.stringify({ active: r.active.map((l) => l.val), expired: r.expired.map((l) => l.val) }))
    """
    out = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r == {"active": ["rude"], "expired": ["spam"]}, r
    import build_snapshot
    assert "l.get(\"exp\")" in open(build_snapshot.__file__).read(), "snapshot rows must keep exp"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
