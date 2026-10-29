"""Record the narrated two-minute walk-through video of LabelLens.

Each scene has one narration line, spoken by Kokoro-82M (Apache-2.0) and shown as a caption. The lines are
synthesized first, so every scene lasts as long as its line; then the walk-through is recorded with Playwright
(title cards, a spotlight on the part being explained, a visible pointer) and the voice is mixed in.
The screencast can fall a few seconds behind the script, so each scene shows a grey level in a strip below the
frame; the voice is placed where that level appears in the recording, and the strip is cropped away.
The census is live, so the labels shown for the example account can differ from run to run.

Serve docs/ first, e.g. `python3 -m http.server 8799 -d docs`; open it as localhost so a proxy bypass applies.
Usage: python -I src/make_video.py <out.mp4> <kokoro_dir> [site URL] [voice]
<kokoro_dir> holds kokoro-v1.0.onnx and voices-v1.0.bin (github.com/thewh1teagle/kokoro-onnx releases).
"""
import glob, json, os, shutil, subprocess, sys, tempfile, time

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro
from playwright.sync_api import sync_playwright

OUT, KDIR = sys.argv[1], sys.argv[2]
URL = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8799/"
VOICE = sys.argv[4] if len(sys.argv) > 4 else "am_michael"
SR, LEAD, TAIL = 24000, 0.35, 0.6  # narration starts LEAD s into its scene; TAIL s of quiet before the next scene
W, H, STRIP, FPS = 1280, 800, 16, 25  # the marker strip sits below the H-pixel frame

HERE = os.path.dirname(os.path.abspath(__file__))
NET = json.load(open(os.path.join(HERE, "..", "docs", "network.json")))
DRV = json.load(open(os.path.join(HERE, "..", "data", "lens_drivers.json")))
DIR = len(json.load(open(os.path.join(HERE, "..", "docs", "labelers.json")))["labelers"])  # services the census asks
S, LP = NET["summary"], NET["lenses"]["post"]
PROT_PCT = round(100 * LP["differs_from_public"]["protective"] / LP["n"])
INERT_PCT = 100 * S["inert"] / S["labels"]
DRV_PCT = 100 * DRV["top_n"] / DRV["n"]
LINES = {
    "title": "On Bluesky, anyone can run a moderation service, called a labeler, and every user picks which ones to trust.",
    "hook": "So the same post can look different to different people. A logged-out visitor sees only Bluesky's own "
            "moderation. LabelLens makes that difference visible.",
    "notice": "Before the first query, LabelLens warns that every labeler it asks sees your IP address. Privacy mode "
              "asks only Bluesky's own labeler.",
    "ask": f"Paste a post or an account. LabelLens asks all {DIR} published labelers about it at once, "
           "from your browser. For the example accounts, services that refuse browser requests are filled in from a collected snapshot.",
    "lenses": "Then it runs the official Bluesky moderation code under four lenses: a logged-out visitor, the twenty "
              "most-liked labelers, the twenty most-liked protective ones, and your own stack.",
    "causes": "Here the lenses disagree, and each card names the labels, and the labelers, that caused its outcome.",
    "stack": "Open your stack and switch labelers on or off, to see which one decides what you would see.",
    "census": "Below is every label in force, by labeler. Retracted labels are struck through, and dashed ones were "
              "never declared, so clients ignore them.",
    "network": f"The Network page shows the ecosystem behind this. Only {S['answering']} of {S['resolvable']} "
               f"endpoints answer, and {S['browser']} let a browser read them. Of {S['labels'] / 1e6:.0f} million "
               f"labels, {INERT_PCT:.0f} percent have no effect.",
    "table": f"On a uniform sample, the protective stack changes how {PROT_PCT} percent of labelled posts look, "
             "mostly because clients apply an author's account labels to their posts. "
             + (f"{DRV_PCT:.0f} percent of those changes carry a label from one service."
                if DRV_PCT > 50 else "Each service's share is listed in the paper."),
    "end": "Try LabelLens in your browser, with no login. The links are in the paper.",
}

OVERLAY_JS = r"""() => {
  if (window.__ov) return; window.__ov = true;
  const css = document.createElement('style'); css.textContent = `
  #__cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:940px;z-index:100;display:none;
    background:rgba(11,11,11,.86);color:#fff;font:600 19px system-ui,sans-serif;padding:11px 20px;border-radius:10px;
    text-align:center;line-height:1.35;box-shadow:0 4px 20px rgba(0,0,0,.25)}
  #__card{position:fixed;inset:0;z-index:90;background:var(--bg);display:flex;align-items:center;justify-content:center;
    opacity:0;pointer-events:none;transition:opacity .45s ease}
  #__card.on{opacity:1} #__card .in{max-width:1080px;padding:0 40px 90px;font-family:system-ui,sans-serif;color:var(--ink)}
  #__card h1{font-size:64px;margin:0 0 10px;letter-spacing:-.02em} #__card h2{font-size:30px;margin:0 0 26px;font-weight:600}
  #__card .sub{font-size:24px;color:var(--muted)} #__card .k{font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
  #__card .four{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  #__card .bx{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;font-size:19px;line-height:1.4}
  #__card .bx b{display:block;margin-bottom:6px} #__card .bx span{font-weight:600}
  #__spot{position:fixed;z-index:80;border-radius:12px;pointer-events:none;box-shadow:0 0 0 4px #eb6834,0 0 0 9999px rgba(10,10,10,.38);
    transition:all .5s ease;display:none}
  #__ptr{position:fixed;z-index:110;width:22px;height:22px;border-radius:50%;background:rgba(235,104,52,.9);border:3px solid #fff;
    box-shadow:0 2px 8px rgba(0,0,0,.35);left:640px;top:400px;display:none;transition:left .7s ease,top .7s ease,transform .15s;pointer-events:none}
  #__ptr.down{transform:scale(.7)}`;
  document.head.appendChild(css);
  for (const id of ['__cap', '__card', '__spot', '__ptr', '__mk']) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d); }
  Object.assign(document.getElementById('__mk').style, {position: 'fixed', left: 0, right: 0, bottom: 0, height: 'STRIPpx',
    zIndex: 200, background: 'rgb(0,0,0)'});
  window.__mark = (v) => { document.getElementById('__mk').style.background = `rgb(${v},${v},${v})`; };
  window.__capt = (t) => { const c = document.getElementById('__cap'); c.textContent = t; c.style.display = t ? 'block' : 'none'; };
  window.__cardShow = (html) => { const c = document.getElementById('__card');
    document.getElementById('__ptr').style.display = 'none';
    if (html) { c.innerHTML = '<div class="in">' + html + '</div>'; c.classList.add('on'); } else c.classList.remove('on'); };
  window.__spotOn = (sel, pad) => { const s = document.getElementById('__spot'); const el = sel && document.querySelector(sel);
    if (!el) { s.style.display = 'none'; return; } const r = el.getBoundingClientRect(); pad = pad || 8;
    Object.assign(s.style, {display: 'block', left: (r.left - pad) + 'px', top: (r.top - pad) + 'px',
      width: (r.width + 2 * pad) + 'px', height: (r.height + 2 * pad) + 'px'}); };
  window.__ptrTo = (sel) => { const el = document.querySelector(sel); if (!el) return; const r = el.getBoundingClientRect();
    const p = document.getElementById('__ptr'); p.style.display = 'block'; p.style.left = (r.left + r.width / 2 - 11) + 'px'; p.style.top = (r.top + r.height / 2 - 11) + 'px'; };
  window.__ptrClick = () => { const p = document.getElementById('__ptr'); p.classList.add('down'); setTimeout(() => p.classList.remove('down'), 180); };
}""".replace("STRIP", str(STRIP))

TITLE = """<h1>LabelLens</h1><h2>Seeing a Bluesky post through other people's moderation</h2>
<div class="sub">WWW 2027 Demo · runs in the browser, no login</div>"""
HOOK = """<div class="k">One post, four people</div><div class="four">
<div class="bx"><b>Logged-out visitor</b>Bluesky's labeler only<br><span style="color:var(--plain)">shown as is</span></div>
<div class="bx"><b>Popular stack</b>20 most-liked labelers<br><span style="color:var(--inform)">info badge</span></div>
<div class="bx"><b>Protective stack</b>20 that hide or warn<br><span style="color:var(--blurred)">behind a warning</span></div>
<div class="bx"><b>Your stack</b>any labelers you pick<br><span style="color:var(--muted)">?</span></div>
</div><div class="sub" style="margin-top:22px">Same item, same moderation code, different subscriptions.</div>"""
END = """<h2>Try it</h2><div class="sub" style="line-height:1.8">Site: <b>seungbum.github.io/labellens</b><br>
Code and data: <b>github.com/seungbum/labellens</b></div>"""


def synth():
    k = Kokoro(os.path.join(KDIR, "kokoro-v1.0.onnx"), os.path.join(KDIR, "voices-v1.0.bin"))
    clips = {}
    for key, text in LINES.items():
        a, sr = k.create(text, voice=VOICE, speed=1.0, lang="en-us")
        assert sr == SR
        nz = np.where(np.abs(a) > 0.01)[0]
        clips[key] = a[max(nz[0] - 1200, 0): nz[-1] + 2400]
    return clips


def level(key):
    return 16 * (list(LINES).index(key) + 2)


def find_scenes(webm, starts):
    """Time at which each scene's marker level first appears in the recording (FPS frames per second)."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", webm, "-vf",
                          f"fps={FPS},crop={W // 2}:{STRIP // 2}:{W // 4}:{H + STRIP // 4},scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    # Levels rise by one step per scene; the encoder may rescale them, so look for each rise, not an exact value.
    seen, i, prev = {}, 0, 0
    for key in sorted(starts, key=starts.get):
        j = next((f for f in range(i, len(raw)) if prev + 9 <= raw[f] < 250), None)
        if j is None:
            raise SystemExit(f"marker for scene {key!r} not found in the recording")
        seen[key], i, prev = j / FPS, j, sorted(raw[j: j + 5])[2]
    return seen


def main():
    clips = synth()
    dur = {k: len(v) / SR for k, v in clips.items()}
    tmp = tempfile.mkdtemp()
    starts = {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    with sync_playwright() as pw:
        # Send only HTTPS through a proxy, so the local site is reached directly.
        args = [f"--proxy-server=https={proxy.split('://')[-1]}"] if proxy else []
        b = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None, headless=True, args=args)
        ctx = b.new_context(viewport={"width": W, "height": H + STRIP}, record_video_dir=tmp,
                            record_video_size={"width": W, "height": H + STRIP})
        t0 = time.monotonic()
        p = ctx.new_page()
        p.emulate_media(color_scheme="light")
        p.goto(URL)
        p.wait_for_selector("#examples button")
        p.evaluate(OVERLAY_JS)
        state = {}

        def scene(key, *, card=None):
            if card is not None:
                p.evaluate("(h) => __cardShow(h)", card)
            state["t"] = time.monotonic()
            starts[key] = state["t"] - t0
            p.evaluate("(t) => __capt(t)", LINES[key])
            p.evaluate("(v) => __mark(v)", level(key))

        def hold(key):  # wait until the scene's line has been spoken
            left = LEAD + dur[key] + TAIL - (time.monotonic() - state["t"])
            if left > 0:
                p.wait_for_timeout(int(left * 1000))

        def point(sel, click=True):
            p.evaluate("(s) => __ptrTo(s)", sel)
            p.wait_for_timeout(800)
            if click:
                p.evaluate("() => __ptrClick()")
                p.click(sel)

        def spot(sel, pad=8):
            p.evaluate("([s, d]) => __spotOn(s, d)", [sel, pad])

        def scroll_to(sel, block="start"):
            p.evaluate("([s, b]) => document.querySelector(s).scrollIntoView({block: b})", [sel, block])
            p.wait_for_timeout(400)

        p.evaluate("(h) => __cardShow(h)", TITLE)
        p.wait_for_timeout(600)
        scene("title", card=TITLE); hold("title")
        scene("hook", card=HOOK); hold("hook")
        p.evaluate("() => __cardShow(null)")
        p.wait_for_timeout(500)

        scene("notice")
        spot("#notice", 8)
        p.wait_for_timeout(1200)
        spot(".privacy", 6)
        hold("notice")
        spot(None)
        point("#notice-ok")
        p.wait_for_timeout(400)

        scene("ask")
        spot("#form", 8)
        p.wait_for_timeout(1500)
        spot(None)
        point("#examples button:first-child")
        p.wait_for_function("document.querySelector('#timing').textContent.includes('Lenses shown')", timeout=60000)
        spot("#progress", 10)
        # Let the recheck of offline services finish too, so the lenses do not re-render later.
        p.wait_for_function("document.querySelector('#timing').textContent.includes('in total')", timeout=90000)
        hold("ask")
        spot(None)

        scene("lenses")
        scroll_to("#lens-summary")
        p.evaluate("window.scrollBy(0, -60)")
        spot("#lenses .lenses", 6); hold("lenses")
        scene("causes")
        spot("#lenses .lens:nth-child(3)", 6); hold("causes")
        spot(None)

        scene("stack")
        point("#lenses details.stack summary")
        p.wait_for_timeout(600)
        scroll_to("#lenses details.stack", "center")
        spot("#lenses .lens:nth-child(4)", 6)
        # Untick the labeler named in the card's first cause (or the first one listed), so the card changes.
        pick = p.evaluate("""() => {
          const picks = [...document.querySelectorAll('#lenses details.stack label.pick')]
          const cause = document.querySelector('#lenses .lens:nth-child(4) .causes li')?.textContent || ''
          const i = Math.max(0, picks.findIndex((l) => cause.endsWith(l.textContent.trim())))
          if (picks[i]) picks[i].id = '__pick'
          return picks.length
        }""")
        if pick:
            p.evaluate("() => __ptrTo('#__pick input')")
            p.wait_for_timeout(800)
            p.evaluate("() => __ptrClick()")
            p.click("#__pick input")
            p.wait_for_timeout(1200)
            spot("#lenses .lens:nth-child(4)", 6)
        hold("stack")
        p.wait_for_timeout(1800)  # let the changed card be seen
        spot(None)

        scene("census")
        scroll_to("#census")
        p.evaluate("window.scrollBy(0, -50)")
        spot("#census", 6); hold("census")
        spot(None)

        scene("network")
        p.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        p.wait_for_timeout(600)
        point('nav.tabs a[href="network.html"]')
        p.wait_for_selector("#tiles .tile")
        p.evaluate(OVERLAY_JS)
        p.evaluate("(t) => __capt(t)", LINES["network"])
        p.evaluate("(v) => __mark(v)", level("network"))
        spot("#tiles", 8); hold("network")
        spot(None)

        scene("table")
        scroll_to("#lens-table", "center")
        spot("#lens-table", 6); hold("table")
        spot(None)
        p.evaluate("window.scrollTo({top: 0})")
        scene("end", card=END); hold("end")
        p.wait_for_timeout(6000)  # let the lagging screencast reach the end card; the tail is trimmed below
        total = time.monotonic() - t0
        ctx.close()
        b.close()
    webm = glob.glob(os.path.join(tmp, "*.webm"))[0]
    seen = find_scenes(webm, starts)
    length = seen["end"] + LEAD + dur["end"] + TAIL + 1.0
    track = np.zeros(int(length * SR), dtype=np.float32)
    for key, a in clips.items():
        s = int((seen[key] + LEAD) * SR)
        track[s: s + len(a)] += a[: len(track) - s]
    wav = os.path.join(tmp, "narration.wav")
    sf.write(wav, track, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-vf", f"fps={FPS},crop={W}:{H}:0:0", "-t", f"{length:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-c:a", "aac", "-b:a", "128k", "-shortest",
                    "-movflags", "+faststart", OUT], check=True)
    shutil.rmtree(tmp)
    print(OUT, round(total, 1), {k: (round(starts[k], 2), round(seen[k], 2)) for k in starts})


if __name__ == "__main__":
    main()
