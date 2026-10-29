"""Time the live census in headless Chromium on items drawn from the lens sample.

Serves a site build (docs/ is the public build; web/local_build/ adds the full snapshot,
see `make local`, and is never published) and records, per item, the time from the click
until the lenses are shown, the first census pass, the recheck, and how many services
answered live or from the snapshot. Writes only timings and counts, no item identifiers.
Usage: python tests/census_eval.py data/lens_sample/sample.jsonl N out.json [--root docs] [--build public] [--vantage "cloud workspace"]
"""
import argparse, asyncio, json, os, random, re, subprocess, sys, time
from playwright.async_api import async_playwright

HERE = os.path.dirname(__file__)
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium")


def pick(sample_path, n, seed=2027):
    rows = [json.loads(l) for l in open(sample_path)]
    posts = [r["subject"] for r in rows if "/app.bsky.feed.post/" in r["subject"]]
    accts = [r["subject"] for r in rows if r["subject"].startswith("did:")]
    rnd = random.Random(seed)
    # Extra candidates replace deleted or hidden items until n censuses have finished.
    return rnd.sample(posts, min(len(posts), 3 * n)) + rnd.sample(accts, min(len(accts), 3 * n))


def num(pattern, text, cast=float):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


async def main(a):
    targets = pick(a.sample, a.n)
    root = os.path.join(HERE, "..", a.root)
    port = "8766"
    srv = subprocess.Popen([sys.executable, "-m", "http.server", port, "-d", root],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    results = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME,
                                        args=[f"--proxy-server=https={proxy.split('://')[-1]}"] if proxy else [])  # HTTPS only via the proxy; the local site stays direct
            done = {"post": 0, "account": 0}
            for t in targets:
                kind = "post" if "/app.bsky.feed.post/" in t else "account"
                if done[kind] >= a.n // 2:
                    continue
                pg = await b.new_page()
                await pg.goto(f"http://localhost:{port}/#" + t)
                try:
                    await pg.wait_for_function("document.querySelector('#timing').textContent.includes('in total') || document.querySelector('#error').textContent", timeout=120000)
                except Exception:
                    results.append({"kind": kind, "error": "timeout"})
                    await pg.close()
                    continue
                err = await pg.inner_text("#error")
                prog = await pg.inner_text("#progress")
                timing = await pg.inner_text("#timing")
                lens = await pg.get_attribute("#timing", "data-lens-seconds")
                answered = num(r"(\d+) answered", prog, int)
                snap = num(r"\((\d+) from", prog, int) or 0
                results.append({
                    "kind": kind, "error": err or None,
                    "asked": num(r"\d+ of (\d+)", prog, int),
                    "answered": answered, "snapshot": snap,
                    "live": answered - snap if answered is not None else None,
                    "labelled_by": num(r"(\d+) have a label", prog, int),
                    "lens_seconds": float(lens) if lens else None,
                    "seconds": num(r"first census pass ([\d.]+) s", timing),
                    "total_seconds": num(r"\(([\d.]+) s in total", timing),
                    "revived": num(r"(\d+) more answered", timing, int),
                    "lens_outcomes": len({await c.get_attribute("class") for c in await pg.query_selector_all(".lens")}),
                })
                if not err:
                    done[kind] += 1
                print(results[-1], flush=True)
                await pg.close()
            await b.close()
    finally:
        srv.terminate()
    json.dump({"run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vantage": a.vantage,
               "build": a.build, "items": results}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sample"); ap.add_argument("n", type=int); ap.add_argument("out")
    ap.add_argument("--root", default="docs")
    ap.add_argument("--build", default="public", choices=["public", "full"])
    ap.add_argument("--vantage", default="cloud workspace")
    asyncio.run(main(ap.parse_args()))
