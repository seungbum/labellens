# Rebuild everything derived from a measurement run.
#   make measure   re-collect from the network (slow; the paper uses GitHub Actions run 39569825801)
#   make derived   directory, snapshot, lens sample and network page data from data/
#   make site      build the static site into docs/
#   make paper     paper/main.pdf
PY ?= .venv/bin/python
PROBE := $(lastword $(sort $(wildcard data/probe_*.jsonl)))

.PHONY: measure derived site paper all
all: derived site paper

measure:
	$(PY) src/list_labelers.py data/labelers.jsonl
	$(PY) src/probe_endpoints.py data/labelers.jsonl data/probe_$$(date -u +%Y%m%d).jsonl
	rm -f data/collect_log.jsonl && $(PY) src/collect.py data/labelers.jsonl data/labels data/collect_log.jsonl
	$(PY) src/analyze.py data/labelers.jsonl data/collect_log.jsonl data/labels data/network_raw.json

derived:
	$(PY) src/build_labelers.py data/labelers.jsonl web/public/labelers.json $(PROBE)
	$(PY) src/build_snapshot.py data/labelers.jsonl $(PROBE) data/collect_log.jsonl data/labels web/public/snapshot data/snapshot_subjects.txt
	$(PY) src/lens_sample.py data/labels data/labelers.jsonl 1000 data/lens_sample
	cd web && node src/lens_eval.mjs ../data/lens_sample/views.json ../data/lens_sample/stacks.json \
		< ../data/lens_sample/sample.jsonl > ../data/lens_sample/verdicts.jsonl
	$(PY) src/lens_drivers.py data/lens_sample data/labelers.jsonl
	$(PY) src/build_network.py data/labelers.jsonl $(PROBE) data/network_raw.json data/lens_sample/verdicts.jsonl web/public/network.json

site:
	cd web && ./build.sh

paper:
	$(PY) src/paper_numbers.py paper/numbers.tex
	cd paper && latexmk -pdf -interaction=nonstopmode -quiet main.tex
