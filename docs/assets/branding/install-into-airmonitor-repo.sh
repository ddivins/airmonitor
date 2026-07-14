#!/usr/bin/env bash
set -euo pipefail

# Run this from the root of the ddivins/airmonitor repository.
if [[ ! -f README.md || ! -d docs ]]; then
  echo "Error: run this from the root of the AirMonitor repository." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p docs/assets

cp "$SCRIPT_DIR/airmonitor-logo-1200px.jpg" docs/assets/airmonitor-logo.jpg
cp "$SCRIPT_DIR/airmonitor-open-graph-1200x630.jpg" docs/assets/airmonitor-open-graph.jpg
cp "$SCRIPT_DIR/favicon.ico" docs/assets/favicon.ico
cp "$SCRIPT_DIR/airmonitor-icon-180.png" docs/assets/apple-touch-icon.png
cp "$SCRIPT_DIR/airmonitor-icon-192.png" docs/assets/airmonitor-icon-192.png
cp "$SCRIPT_DIR/airmonitor-icon-512.png" docs/assets/airmonitor-icon-512.png

# Remove the incorrect reconstructed SVG and the temporary connector test file.
rm -f docs/assets/airmonitor-logo.svg
rm -f docs/assets/.connector-test

python3 - <<'PY'
from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
text = text.replace(
    'src="docs/assets/airmonitor-logo.svg"',
    'src="docs/assets/airmonitor-logo.jpg"'
)
path.write_text(text, encoding="utf-8")
PY

echo
echo "Prepared approved AirMonitor branding assets."
echo "Review with:"
echo "  git status"
echo "  git diff -- README.md"
echo
echo "Then commit with:"
echo '  git add README.md docs/assets'
echo '  git commit -m "Use approved AirMonitor logo artwork"'
echo '  git push'
