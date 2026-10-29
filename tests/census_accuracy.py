"""Compare the live census with the labels derived from the collected streams.

For N seeded subjects of the lens sample, the census runs in headless Chromium on a site
build (?debug=1 exposes its final result) and is compared label by label with the labels
in force at collection time (data/lens_sample/sample.jsonl). Each difference is put in
one class:
  missing_service_offline     the service did not answer the census (offline, timeout, 429)
  missing_nocors_no_snapshot  the service allows no browser queries and the build has no snapshot for the item
  stale_snapshot              the snapshot no longer matches the stream (it was built from the same run)
  new_after_collection        the census has a label issued after the service was collected
  outside_window              the census has an older label of a service collected over a recent window only
  other                       anything else, e.g. a label retracted after collection
Writes counts only, no item identifiers.
Usage: python tests/census_accuracy.py data/lens_sample/sample.jsonl data/collect_log.jsonl N out.json [--root docs] [--build public]
"""
import argparse, asyncio, collections, json, os, random, subprocess, sys, time
from playwright.async_api import async_playwright

HERE = os.path.dirname(__file__)
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium")
ANSWER = ("ok", "snapshot")
OFFLINE = ("error", "timeout", "ratelimited")


def classify(truth, census, logs):
    """Return a Counter of difference classes for one item."""
    status = {r["did"]: r["status"] for r in census}
    got = {(r["did"], l["uri"], l["val"]): l for r in census if r["status"] in ANSWER for l in r["active"]}
    want = {(l["src"], l["uri"], l["val"]): l for l in truth}
    diff = collections.Counter()
    for k in want.keys() - got.keys():
        st = status.get(k[0])
        if st in OFFLINE or st is None:
            diff["missing_service_offline"] += 1
        elif st == "nocors":
            diff["missing_nocors_no_snapshot"] += 1
        elif st == "snapshot":
            diff["stale_snapshot"] += 1
        else:
            diff["other"] += 1
    for k in got.keys() - want.keys():
        log = logs.get(k[0], {})
        cts = got[k].get("cts") or ""
        if log.get("finished_at") and cts > log["finished_at"]:
            diff["new_after_collection"] += 1
        elif log.get("start"):
            diff["outside_window"] += 1
        elif status.get(k[0]) == "snapshot":
            diff["stale_snapshot"] += 1
        else:
            diff["other"] += 1
    return diff, len(want), len(want.keys() & got.keys())


async def main(a):
    rows = [json.loads(l) for l in open(a.sample)]
    random.Random(2027).shuffle(rows)
    logs = {json.loads(l)["did"]: json.loads(l) for l in open(a.log)}
    root = os.path.join(HERE, "..", a.root)
    port = "8767"
    srv = subprocess.Popen([sys.executable, "-m", "http.server", port, "-d", root],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    items, gone = [], 0
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME,
                                        args=[f"--proxy-server=https={proxy.split('://')[-1]}"] if proxy else [])  # HTTPS only via the proxy; the local site stays direct
            for row in rows:
                if len(items) >= a.n:
                    break
                pg = await b.new_page()
                await pg.goto(f"http://localhost:{port}/?debug=1#" + row["subject"])
                try:
                    await pg.wait_for_function("(window.__labellens && window.__labellens.done) || document.querySelector('#error').textContent", timeout=120000)
                except Exception:
                    await pg.close()
                    continue
                if await pg.inner_text("#error"):
                    gone += 1  # deleted or hidden since collection; the next subject replaces it
                    await pg.close()
                    continue
                census = await pg.evaluate("window.__labellens.census")
                await pg.close()
                diff, n_want, n_both = classify(row["labels"], census, logs)
                items.append({"kind": "account" if row["subject"].startswith("did:") else "post",
                              "exact": not diff, "labels": n_want, "matched": n_both, "diff": dict(diff)})
                print(len(items), items[-1], flush=True)
            await b.close()
    finally:
        srv.terminate()
    total = collections.Counter()
    for it in items:
        total.update(it["diff"])
    out = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "build": a.build, "vantage": a.vantage,
           "n": len(items), "gone": gone, "exact": sum(it["exact"] for it in items),
           "labels": sum(it["labels"] for it in items), "matched": sum(it["matched"] for it in items),
           "items_with": {k: sum(1 for it in items if it["diff"].get(k)) for k in total},
           "differences": dict(total), "items": items}
    json.dump(out, open(a.out, "w"), indent=1)
    print({k: v for k, v in out.items() if k != "items"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sample"); ap.add_argument("log"); ap.add_argument("n", type=int); ap.add_argument("out")
    ap.add_argument("--root", default="docs")
    ap.add_argument("--build", default="public", choices=["public", "full"])
    ap.add_argument("--vantage", default="cloud workspace")
    asyncio.run(main(ap.parse_args()))
