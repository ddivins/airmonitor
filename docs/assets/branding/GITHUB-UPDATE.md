# Install the approved logo into `ddivins/airmonitor`

The current repository contains a reconstructed SVG that does not match the approved logo.
This pack uses the approved JPEG artwork as the visual master.

## Automated method

1. Extract this ZIP.
2. Open Terminal.
3. Change to the root of your local AirMonitor repository.
4. Run:

```bash
/path/to/AirMonitor-Approved-Logo-Web-Pack/install-into-airmonitor-repo.sh
```

5. Review and publish:

```bash
git status
git diff -- README.md
git add README.md docs/assets
git commit -m "Use approved AirMonitor logo artwork"
git push
```

The script:

- installs the approved 1200-pixel logo as `docs/assets/airmonitor-logo.jpg`
- updates `README.md` to display that file
- adds Open Graph and web icon assets
- removes the incorrect reconstructed `airmonitor-logo.svg`
- removes the accidental `.connector-test` placeholder

## Manual method

From the repository root:

```bash
mkdir -p docs/assets

cp /path/to/pack/airmonitor-logo-1200px.jpg docs/assets/airmonitor-logo.jpg
cp /path/to/pack/airmonitor-open-graph-1200x630.jpg docs/assets/airmonitor-open-graph.jpg
cp /path/to/pack/favicon.ico docs/assets/favicon.ico
cp /path/to/pack/airmonitor-icon-180.png docs/assets/apple-touch-icon.png
cp /path/to/pack/airmonitor-icon-192.png docs/assets/airmonitor-icon-192.png
cp /path/to/pack/airmonitor-icon-512.png docs/assets/airmonitor-icon-512.png

rm -f docs/assets/airmonitor-logo.svg
rm -f docs/assets/.connector-test
```

In `README.md`, change:

```html
<img src="docs/assets/airmonitor-logo.svg"
```

to:

```html
<img src="docs/assets/airmonitor-logo.jpg"
```

Then:

```bash
git add README.md docs/assets
git commit -m "Use approved AirMonitor logo artwork"
git push
```

## Important note about SVG

`airmonitor-logo.svg` in this pack embeds the approved JPEG inside an SVG container. It
preserves the appearance but is not a true path-based vector redraw. The approved JPEG
remains the visual source of truth.
