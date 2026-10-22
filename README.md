# LabelLens

LabelLens shows how one Bluesky post or account looks to people who trust different moderation services.

**Try it:** https://seungbum.github.io/labellens/ (no login; runs in your browser).

On Bluesky, moderation is split into *labels*: any account can run a labeling service (a *labeler*), and every
user picks which labelers to subscribe to. LabelLens asks every public labeler about an item at once (the
*census*), then renders the item through several subscription sets (the *lenses*) with the moderation code of the
official client library, so the differences are visible side by side.

- **Inspect**: paste a post link, an `at://` URI or a handle. Everything runs in the browser against public APIs.
- **Network**: a measurement snapshot of all declared labelers: reachability, label volume, retractions,
  labels with no effect, and time to label.

A two-minute narrated walk-through is in [`docs/labellens_demo.mp4`](docs/labellens_demo.mp4) (recorded with `src/make_video.py`;
the census in it is live, so the labels shown can differ from what the site shows today).

## Layout

| Path | What it is |
|---|---|
| `web/` | The site source (`src/main.js` census and lenses, `src/network.js` network page). `web/build.sh` builds into `docs/`. |
| `docs/` | The built static site, served by GitHub Pages. |
| `src/list_labelers.py` | Enumerates labeler services from the relay and resolves their endpoints. |
| `src/probe_endpoints.py` | Checks whether each endpoint answers `queryLabels` and allows browser (CORS) reads. |
| `src/collect.py` | Replays each labeler's label stream (`subscribeLabels`) into `data/labels/`. |
| `src/analyze.py` | Summarises the collected labels into per-labeler statistics. |
| `src/build_snapshot.py` | Builds the static fallback for labelers a browser cannot query (example accounts only, or everything for a local build). |
| `src/make_video.py` | Records the narrated walk-through video (Kokoro-82M voice, Playwright). |

## Running it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/list_labelers.py data/labelers.jsonl
.venv/bin/python src/probe_endpoints.py data/labelers.jsonl data/probe.jsonl
.venv/bin/python src/collect.py data/labelers.jsonl data/labels data/collect_log.jsonl
cd web && npm ci && ./build.sh
```

## Data

LabelLens reads only public data and stores nothing about visitors. The published data holds aggregate figures
per labeling service, plus, for the services a browser cannot query, the labels in force at collection time for
the organisational example accounts only (`data/snapshot_subjects.txt`). Labels about other accounts and the
collected raw label logs are not published. Sources, licences, terms and removal requests:
[`DATA_LICENSES.md`](DATA_LICENSES.md).

## License

MIT
