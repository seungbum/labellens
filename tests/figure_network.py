"""Screenshot the Network page summary (tiles and label-volume bars) for the paper.

Usage: python tests/figure_network.py paper/figures/ui_network.png
"""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
W = 900
# Show ten bars and drop the explanatory notes, so the crop stays readable at column width.
FIGURE_CSS = ".hbar:nth-child(n+11){display:none} #volume-note{display:none} .tiles{grid-template-columns:repeat(5,1fr)}"


def main(png):
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8769", "-d", ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME)
            pg = b.new_page(viewport={"width": W, "height": 900}, device_scale_factor=2)
            pg.emulate_media(color_scheme="light")
            pg.goto("http://localhost:8769/network.html")
            pg.wait_for_selector("#volume .hbar")
            pg.add_style_tag(content=FIGURE_CSS)
            top = pg.eval_on_selector("#tiles", "e => e.getBoundingClientRect().top + window.scrollY")
            bottom = pg.eval_on_selector("#volume", "e => e.getBoundingClientRect().bottom + window.scrollY")
            pg.screenshot(path=png, full_page=True, clip={"x": 0, "y": top - 10, "width": W, "height": bottom - top + 20})
            b.close()
    finally:
        srv.terminate()


if __name__ == "__main__":
    main(sys.argv[1])
