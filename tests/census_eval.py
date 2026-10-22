"""Time the live census in headless Chromium on items drawn from the lens sample.

Writes only timings and counts (no item identifiers) to the output JSON.
Usage: python tests/census_eval.py data/lens_sample/sample.jsonl N out.json
"""
import asyncio, json, os, random, re, subprocess, sys, time
from playwright.async_api import async_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def pick(sample_path, n, seed=2027):
    rows = [json.loads(l) for l in open(sample_path)]
    posts = [r["subject"] for r in rows if "/app.bsky.feed.post/" in r["subject"]]
    accts = [r["subject"] for r in rows if r["subject"].startswith("did:")]
    rnd = random.Random(seed)
    # Extra candidates replace deleted or hidden items until n censuses have finished.
    return rnd.sample(posts, n) + rnd.sample(accts, n)


async def main(sample_path, n, out_path):
    targets = pick(sample_path, int(n))
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8766", "-d", ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    results = []
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME,
                                        proxy={"server": proxy, "bypass": "localhost"} if proxy else None)
            done = {"post": 0, "account": 0}
            for t in targets:
                kind = "post" if "/app.bsky.feed.post/" in t else "account"
                if done[kind] >= int(n) // 2:
                    continue
                pg = await b.new_page()
                await pg.goto("http://localhost:8766/#" + t)
                try:
                    await pg.wait_for_function("document.querySelector('#timing').textContent.includes('in total') || document.querySelector('#error').textContent", timeout=120000)
                except Exception:
                    results.append({"kind": kind, "error": "timeout"})
                    await pg.close()
                    continue
                err = await pg.inner_text("#error")
                prog = await pg.inner_text("#progress")
                timing = await pg.inner_text("#timing")
                nums = [int(x) for x in re.findall(r"\d+", prog.split("(")[0])]
                snap = re.search(r"\((\d+) from", prog)
                sec = re.search(r"took ([\d.]+) s", timing)
                total = re.search(r"\(([\d.]+) s in total", timing)
                revived = re.search(r"(\d+) more answered", timing)
                results.append({
                    "kind": kind, "error": err or None,
                    "asked": nums[1] if len(nums) > 1 else None,
                    "answered": int(re.search(r"(\d+) answered", prog).group(1)) if "answered" in prog else None,
                    "snapshot": int(snap.group(1)) if snap else 0,
                    "labelled_by": int(re.search(r"(\d+) have a label", prog).group(1)) if "have a label" in prog else None,
                    "seconds": float(sec.group(1)) if sec else None,
                    "total_seconds": float(total.group(1)) if total else None,
                    "revived": int(revived.group(1)) if revived else None,
                    "lens_outcomes": len({await c.get_attribute("class") for c in await pg.query_selector_all(".lens")}),
                })
                if not err:
                    done[kind] += 1
                print(results[-1], flush=True)
                await pg.close()
            await b.close()
    finally:
        srv.terminate()
    json.dump({"run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vantage": "cloud workspace",
               "items": results}, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
