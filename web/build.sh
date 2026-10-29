#!/bin/sh
# Build the static site into ../docs (served by GitHub Pages).
set -e
cd "$(dirname "$0")"
mkdir -p ../docs
# The public site may only carry a snapshot limited to the example accounts
# (src/build_snapshot.py with data/snapshot_subjects.txt); never publish the full one.
# A full snapshot for local use belongs in web/local_build/ (see Makefile), never in public/.
python3 ../tests/check_snapshot.py public/snapshot || exit 1
npx esbuild src/main.js --bundle --minify --format=iife --target=es2020 --outfile=../docs/app.js
npx esbuild src/network.js --bundle --minify --format=iife --target=es2020 --outfile=../docs/network.js
cp *.html style.css ../docs/
rm -rf ../docs/snapshot
cp -r public/* ../docs/
touch ../docs/.nojekyll
# Defence in depth: check what actually landed in the Pages directory.
python3 ../tests/check_snapshot.py ../docs/snapshot || { rm -rf ../docs/snapshot; exit 1; }
