#!/bin/sh
# Build the static site into ../docs (served by GitHub Pages).
set -e
cd "$(dirname "$0")"
mkdir -p ../docs
npx esbuild src/main.js --bundle --minify --format=iife --target=es2020 --outfile=../docs/app.js
npx esbuild src/network.js --bundle --minify --format=iife --target=es2020 --outfile=../docs/network.js
cp *.html style.css ../docs/
# The public site may only carry a snapshot limited to the example accounts
# (src/build_snapshot.py with data/snapshot_subjects.txt); never publish the full one.
if [ -f public/snapshot/index.json ] && ! grep -q '"subjects"' public/snapshot/index.json; then
  echo "refusing to publish a snapshot without a subjects list (web/public/snapshot)" >&2
  exit 1
fi
rm -rf ../docs/snapshot
cp -r public/* ../docs/
touch ../docs/.nojekyll
