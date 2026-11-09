#!/bin/bash
# Builds dist/Deal Finder.app and dist/DealFinder-mac.zip from this repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/Deal Finder.app"
rm -rf "$DIST" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/macos/launcher.sh" "$APP/Contents/MacOS/DealFinder"
chmod 755 "$APP/Contents/MacOS/DealFinder"
cp -R "$ROOT/dealfinder" "$ROOT/requirements.txt" "$ROOT/config.example.yaml" "$APP/Contents/Resources/app/"
mkdir -p "$APP/Contents/Resources/app/imports" && cp "$ROOT/imports/example.csv" "$APP/Contents/Resources/app/imports/"
echo "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)-$(date +%Y%m%d%H%M%S)" > "$APP/Contents/Resources/app/VERSION"
find "$APP" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$ROOT/macos/HOW-TO-OPEN.txt" "$DIST/"
(cd "$DIST" && zip -qry DealFinder-mac.zip "Deal Finder.app" HOW-TO-OPEN.txt)
echo "Built $DIST/DealFinder-mac.zip"
