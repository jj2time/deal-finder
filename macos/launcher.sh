#!/bin/bash
# Deal Finder for Mac. Double-click the app: first time it sets itself up (a few minutes),
# then it starts in the background and opens the dashboard in your browser.
set -u
APP_DIR="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
SUPPORT="$HOME/Library/Application Support/Deal Finder"
PORT=8765
URL="http://127.0.0.1:$PORT"
LOG="$SUPPORT/dealfinder.log"
mkdir -p "$SUPPORT"
export DEALFINDER_HOME="$SUPPORT"
export PYTHONDONTWRITEBYTECODE=1

notify() { osascript -e "display notification \"$1\" with title \"Deal Finder\"" >/dev/null 2>&1; }
fail() {
  osascript -e "display dialog \"Deal Finder couldn't start: $1\n\nDetails are in:\n$LOG\" with title \"Deal Finder\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1
  exit 1
}

# Already running? Open it — unless it's an older version, which is stopped and replaced.
APP_VERSION="$(cat "$APP_DIR/VERSION" 2>/dev/null || echo unknown)"
if RUNNING="$(curl -fs "$URL/health")"; then
  case "$RUNNING" in
    *"\"$APP_VERSION\""*) open "$URL"; exit 0 ;;
  esac
  echo "=== Replacing running version with $APP_VERSION $(date) ===" >>"$LOG"
  curl -fs -X POST -o /dev/null "$URL/quit"
  for _ in $(seq 1 20); do curl -fs -o /dev/null "$URL/health" || break; sleep 0.5; done
fi

VENV="$SUPPORT/venv"
REQ_HASH="$(shasum "$APP_DIR/requirements.txt" | cut -c1-12)"
STAMP="$VENV/.installed-$REQ_HASH"
if [ ! -f "$STAMP" ]; then
  notify "Setting up for the first time. This takes a few minutes; your browser opens when it's ready."
  echo "=== Setup $(date) ===" >>"$LOG"
  UV="$(find "$SUPPORT/uv" -type f -name uv -perm -u+x 2>/dev/null | head -1)"
  if [ -z "$UV" ]; then
    # uv installs a private copy of Python just for Deal Finder; nothing else on your Mac changes.
    curl -LsSf https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR="$SUPPORT/uv" INSTALLER_NO_MODIFY_PATH=1 UV_NO_MODIFY_PATH=1 sh >>"$LOG" 2>&1 \
      || fail "couldn't download the installer. Check your internet connection."
    UV="$(find "$SUPPORT/uv" -type f -name uv -perm -u+x 2>/dev/null | head -1)"
    [ -n "$UV" ] || fail "the installer didn't finish."
  fi
  rm -rf "$VENV"
  "$UV" venv --python 3.12 "$VENV" >>"$LOG" 2>&1 || fail "couldn't set up Python."
  "$UV" pip install --python "$VENV/bin/python" -r "$APP_DIR/requirements.txt" >>"$LOG" 2>&1 \
    || fail "couldn't install the components it needs."
  touch "$STAMP"
fi

cd "$APP_DIR" || fail "the app's files are missing."
echo "=== Start $(date) ===" >>"$LOG"
nohup "$VENV/bin/python" -m dealfinder run --port "$PORT" >>"$LOG" 2>&1 &
for _ in $(seq 1 60); do
  if curl -fs -o /dev/null "$URL/health"; then open "$URL"; exit 0; fi
  sleep 0.5
done
fail "it didn't start in time."
