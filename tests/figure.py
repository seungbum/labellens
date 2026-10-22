"""Screenshot the Inspect view for the paper figure and record what it shows.

Usage: python tests/figure.py TARGET paper/figures/ui_inspect.png data/figure_ui.json
"""
import asyncio, json, os, re, subprocess, sys, time
from playwright.async_api import async_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
W = 1500
# Figure-only layout: four lens cards in one row, without the per-card footnotes.
FIGURE_CSS = """
.wrap { max-width: 1500px; }
.lenses { grid-template-columns: repeat(4, 1fr) !important; }
.lens p.small, .stack, #timing { display: none; }
.subject-text { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
"""


async def main(target, png, meta):
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8768", "-d", ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME,
                                        proxy={"server": proxy, "bypass": "localhost"} if proxy else None)
            pg = await b.new_page(viewport={"width": W, "height": 900}, device_scale_factor=2)
            await pg.goto("http://localhost:8768/#" + target)
            await pg.wait_for_function("document.querySelector('#timing').textContent.includes('in total')", timeout=120000)
            await pg.add_style_tag(content=FIGURE_CSS)
            prog = await pg.inner_text("#progress")
            classes = {await c.get_attribute("class") for c in await pg.query_selector_all(".lens")}
            # Crop from the item to the end of the lens cards.
            top = await pg.eval_on_selector("#results", "e => e.getBoundingClientRect().top + window.scrollY")
            bottom = await pg.eval_on_selector("#lenses", "e => e.getBoundingClientRect().bottom + window.scrollY")
            await pg.screenshot(path=png, full_page=True,
                                clip={"x": 0, "y": top - 10, "width": W, "height": bottom - top + 20})
            json.dump({"target": target, "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "progress": prog, "outcomes": len(classes),
                       "labelled_by": int(re.search(r"(\d+) have a label", prog).group(1))},
                      open(meta, "w"), indent=1)
            await b.close()
    finally:
        srv.terminate()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
