# Data, licences and terms

What LabelLens reads, what this repository and the site publish, and the terms that apply. Checked against the
sources on 2026-10-22.

## Sources

| Source | How it is used | Terms |
|---|---|---|
| Bluesky public AppView (`public.api.bsky.app`) | The visitor's browser reads the inspected post or profile and the labelers' declared label definitions. Nothing is stored. | [Bluesky Terms of Service](https://bsky.social/about/support/tos) (users keep the rights to their posts), [Developer Guidelines](https://docs.bsky.app/docs/support/developer-guidelines) (no spam or automated interactions, a way to have content removed, a public contact address) |
| Labeler services (`com.atproto.label.queryLabels`) | The visitor's browser asks every declared labeler about the inspected item. Nothing is stored. | [AT Protocol label specification](https://atproto.com/specs/label): labelers may make their labels publicly available through these endpoints. |
| Labeler label streams (`com.atproto.label.subscribeLabels`) | The measurement replays each service's stream once, one connection per service (parallel cursor ranges for the largest one), with an identifying user agent. | Same specification. Raw logs name individual accounts and are never committed or published. |
| Labeler directory (relay and PLC directory) | List of declared labeler services and their endpoints. | Public protocol data about services. |

## What is published

- `docs/labelers.json`, `docs/network.json`, `data/*.jsonl`, `data/network_raw.json`: figures per labeler
  service. The only identifiers in them are the labelers' own DIDs and handles; label values are left out of the
  per-labeler table because some describe people (pronouns, political affiliation).
- `docs/snapshot/`: labels issued by the services that do not allow browser queries (no CORS header), **only for
  the organisational example accounts** listed in `data/snapshot_subjects.txt`. The site does not republish labels
  about any other account or post. A full snapshot can be built locally with `src/build_snapshot.py` without a
  subjects file; it stays on that machine (`make local` writes it to `web/local_build/`, which is git-ignored),
  and `web/build.sh` plus a CI check refuse to publish it.
- No visitor data is collected. The visitor's browser contacts Bluesky and the labelers directly, so each of them
  sees the visitor's IP address and the item asked about. The site says so before the first query, and privacy
  mode limits queries to Bluesky's own labeler.

## Software and models

| Component | Licence | Use |
|---|---|---|
| [`@atproto/api`](https://github.com/bluesky-social/atproto/blob/main/LICENSE.txt) | MIT or Apache-2.0 | Bundled into `docs/app.js` (moderation decisions). Copyright (c) 2022-2026 Bluesky Social PBC, and Contributors. |
| esbuild, cbor2, websockets, requests, Playwright | MIT / BSD / Apache-2.0 | Build and measurement tools, not redistributed. |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Apache-2.0 / MIT | Synthetic voice of the demo video. |

## Removal requests

Open an issue on this repository or write to seungbum.ju@samsung.com. Snapshot entries are removed on request and
whenever the snapshot is rebuilt.
