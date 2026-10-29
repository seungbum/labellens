# Rebuild everything derived from a measurement run.
#   make measure   re-collect from the network (slow; the paper uses a run from a cloud workspace on the
#                  date in data/probe_*.jsonl; data/actions_20261021/ holds the earlier GitHub Actions run)
#   make derived   directory, snapshot, lens sample and network page data from data/
#   make site      build the static site into docs/
#   make local     the site plus the full snapshot in web/local_build/ (never published)
#   make evaluate  census timing (public and full build), accuracy and paper figures in headless Chromium
#   make paper     paper/main.pdf
PY ?= .venv/bin/python
PROBE := $(lastword $(sort $(wildcard data/probe_*.jsonl)))

.PHONY: measure derived site local evaluate paper all
all: derived site paper

measure:
	$(PY) src/list_labelers.py data/labelers.jsonl
	$(PY) src/probe_endpoints.py data/labelers.jsonl data/probe_$$(date -u +%Y%m%d).jsonl
	rm -f data/collect_log.jsonl && $(PY) src/collect.py data/labelers.jsonl data/labels data/collect_log.jsonl
	$(PY) src/mark_missing.py data/labelers.jsonl data/collect_log.jsonl
	# The largest service was re-collected over parallel ranges (one connection was too slow):
	# $(PY) src/collect_split.py data/labelers.jsonl data/labels data/collect_log.jsonl did:plc:uac6er53o2pvr5y2qmvaf7hw 12
	$(PY) src/analyze.py data/labelers.jsonl data/collect_log.jsonl data/labels data/network_raw.json

derived:
	$(PY) src/build_labelers.py data/labelers.jsonl web/public/labelers.json $(PROBE)
	$(PY) src/build_snapshot.py data/labelers.jsonl $(PROBE) data/collect_log.jsonl data/labels web/public/snapshot data/snapshot_subjects.txt
	$(PY) src/lens_sample.py data/labels data/labelers.jsonl 1000 data/lens_sample
	cd web && node src/lens_eval.mjs ../data/lens_sample/views.json ../data/lens_sample/stacks.json \
		< ../data/lens_sample/sample.jsonl > ../data/lens_sample/verdicts.jsonl
	$(PY) src/lens_drivers.py data/lens_sample data/labelers.jsonl data/lens_drivers.json
	$(PY) src/build_network.py data/labelers.jsonl $(PROBE) data/network_raw.json data/lens_sample/verdicts.jsonl web/public/network.json

site:
	cd web && ./build.sh

# A build with the full snapshot, for local evaluation only: web/local_build/ is never published.
local: site
	rm -rf web/local_build && mkdir -p web/local_build && cp -r docs/. web/local_build/ && rm -rf web/local_build/snapshot
	$(PY) src/build_snapshot.py data/labelers.jsonl $(PROBE) data/collect_log.jsonl data/labels web/local_build/snapshot

evaluate: local
	$(PY) tests/census_eval.py data/lens_sample/sample.jsonl 20 data/census_eval_public.json --root docs --build public
	$(PY) tests/census_eval.py data/lens_sample/sample.jsonl 20 data/census_eval_full.json --root web/local_build --build full
	$(PY) tests/census_accuracy.py data/lens_sample/sample.jsonl data/collect_log.jsonl 200 data/census_accuracy.json --root docs --build public
	$(PY) tests/figure.py nytimes.com paper/figures/ui_inspect.png data/figure_ui.json
	$(PY) tests/figure_network.py paper/figures/ui_network.png

paper:
	$(PY) src/paper_numbers.py paper/numbers.tex
	cd paper && latexmk -pdf -interaction=nonstopmode -quiet main.tex
