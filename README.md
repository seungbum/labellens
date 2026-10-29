# LabelLens

LabelLens shows how one Bluesky post or account looks to people who trust different moderation services.

**Try it:** https://seungbum.github.io/labellens/ (no login; runs in your browser).

On Bluesky, moderation is split into *labels*: any account can run a labeling service (a *labeler*), and every
user picks which labelers to subscribe to. LabelLens asks every public labeler about an item at once (the
*census*), then renders the item through several subscription sets (the *lenses*) with the moderation code of the
official client library, so the differences are visible side by side.

- **Inspect**: paste a post link, an `at://` URI or a handle. Everything runs in the browser against public APIs,
  so every labeler you query sees your IP address; **privacy mode** asks only Bluesky's own labeler.
- **Network**: a measurement snapshot of all declared labelers: reachability, label volume, retractions,
  labels with no effect, and time to label.

A two-minute narrated walk-through is in [`docs/labellens_demo.mp4`](docs/labellens_demo.mp4) (recorded with `src/make_video.py`
on 2026-10-29 from the published site; the census in it is live, so the labels shown can differ from what the site
shows today, while the Network figures and the narration come from the 2026-10-28 measurement).

## Layout

| Path | What it is |
|---|---|
| `web/` | The site source (`src/main.js` census and lenses, `src/network.js` network page). `web/build.sh` builds into `docs/`. |
| `docs/` | The built static site, served by GitHub Pages. |
| `src/list_labelers.py` | Enumerates labeler services from the relay and resolves their endpoints. |
| `src/probe_endpoints.py` | Checks whether each endpoint answers `queryLabels` and allows browser (CORS) reads. |
| `src/collect.py` | Replays each labeler's label stream (`subscribeLabels`) into `data/labels/`, resuming streams that stop early and logging why each one stopped. |
| `src/collect_split.py` | Replays one very large stream over parallel cursor ranges. |
| `src/mark_missing.py` | Logs labelers the collector never reached, so every labeler has one log line. |
| `src/analyze.py` | Summarises the collected labels into per-labeler statistics. |
| `src/build_snapshot.py` | Builds the static fallback for labelers a browser cannot query (example accounts only, or everything for a local build). |
| `src/lens_sample.py`, `web/src/lens_eval.mjs` | Offline lens evaluation on a uniform sample (Table 1 of the paper), with leave-one-out variants of the protective stack. |
| `src/paper_numbers.py` | Writes every number in the paper to `paper/numbers.tex`. |
| `tests/` | `test_regressions.py` (snapshot guard, collection resume, snapshot expiry), `check_snapshot.py` (the publish guard), `census_eval.py` and `census_accuracy.py` (census timing and accuracy in headless Chromium), figure scripts. |
| `src/make_video.py` | Records the narrated walk-through video (Kokoro-82M voice, Playwright). |

## Running it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/list_labelers.py data/labelers.jsonl
.venv/bin/python src/probe_endpoints.py data/labelers.jsonl data/probe.jsonl
.venv/bin/python src/collect.py data/labelers.jsonl data/labels data/collect_log.jsonl
cd web && npm ci && ./build.sh
```

`make derived site paper` rebuilds everything from a collection; `make local` adds a build with the full snapshot
in `web/local_build/` for local evaluation, which is never published. `web/build.sh` and the `Snapshot guard`
workflow refuse any published snapshot that holds labels about accounts outside `data/snapshot_subjects.txt`.

The paper's measurement ran from a cloud workspace on the date of `data/probe_*.jsonl`; the raw label logs were
deleted after analysis. `data/actions_20261021/` holds an earlier run from a GitHub-hosted runner, and
`data/container_20261021/` an earlier, incomplete run from a cloud workspace.

## Data

LabelLens reads only public data and stores nothing about visitors. The published data holds aggregate figures
per labeling service, plus, for the services a browser cannot query, the labels in force at collection time for
the organisational example accounts only (`data/snapshot_subjects.txt`). Labels about other accounts and the
collected raw label logs are not published. Sources, licences, terms and removal requests:
[`DATA_LICENSES.md`](DATA_LICENSES.md).

## License

MIT
