"""Headless smoke test: load the site, inspect one target, print what rendered."""
import asyncio, os, sys, subprocess, time
from playwright.async_api import async_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs")


async def main(target, shot):
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "-d", ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", proxy={"server": proxy, "bypass": "localhost,127.0.0.1"} if proxy else None)
            pg = await b.new_page(viewport={"width": 1280, "height": 900})
            pg.on("console", lambda m: m.type in ("error",) and print("console:", m.text[:200]))
            await pg.goto("http://localhost:8765/#" + target)
            await pg.wait_for_function("document.querySelector('#timing').textContent.includes('in total') || document.querySelector('#error').textContent", timeout=90000)
            print("error:", await pg.inner_text("#error"))
            print("progress:", await pg.inner_text("#progress"))
            print("timing:", await pg.inner_text("#timing"))
            print("summary:", await pg.inner_text("#lens-summary"))
            for t in await pg.query_selector_all(".lens"):
                print("LENS:", (await t.inner_text()).replace("\n", " | ")[:300])
            rows = await pg.query_selector_all(".census-row")
            print("census rows:", len(rows))
            for r in rows[:8]:
                print("  ", (await r.inner_text()).replace("\n", " | ")[:200])
            await pg.screenshot(path=shot, full_page=True)
            await b.close()
    finally:
        srv.terminate()


asyncio.run(main(sys.argv[1], sys.argv[2]))
