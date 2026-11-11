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

APP_VERSION="$(cat "$APP_DIR/VERSION" 2>/dev/null || echo unknown)"
is_current() { curl -fs -m 5 "$URL/health" 2>/dev/null | grep -q "\"$APP_VERSION\""; }
port_in_use() { curl -s -m 3 -o /dev/null "$URL/health"; }

stop_old() {
  # 1. Ask the running copy to stop.
  curl -s -m 5 -X POST -o /dev/null "$URL/quit"
  for _ in $(seq 1 20); do port_in_use || return 0; sleep 0.5; done
  # 2. Still there: stop Deal Finder's own process on this port (only Python processes running dealfinder).
  echo "Old copy didn't stop when asked; stopping it." >>"$LOG"
  for pid in $(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null); do
    if ps -p "$pid" -o command= 2>/dev/null | grep -q "dealfinder"; then kill "$pid" 2>/dev/null; fi
  done
  for _ in $(seq 1 10); do port_in_use || return 0; sleep 0.5; done
  for pid in $(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null); do
    if ps -p "$pid" -o command= 2>/dev/null | grep -q "dealfinder"; then kill -9 "$pid" 2>/dev/null; fi
  done
  for _ in $(seq 1 10); do port_in_use || return 0; sleep 0.5; done
  return 1
}

# Already running this version? Just open it. An older copy is stopped and replaced.
if is_current; then open "$URL"; exit 0; fi
if port_in_use; then
  echo "=== Replacing running copy ($(curl -s -m 5 "$URL/health")) with $APP_VERSION $(date) ===" >>"$LOG"
  if ! stop_old; then
    if curl -s -m 3 "$URL/health" | grep -q '"ok"'; then
      fail "an older copy of Deal Finder is still running and won't stop. Restart your Mac, then open Deal Finder again."
    else
      fail "another program on your Mac is using Deal Finder's port ($PORT). Restart your Mac, then open Deal Finder again."
    fi
  fi
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
start_new() {
  echo "=== Start $APP_VERSION $(date) ===" >>"$LOG"
  nohup "$VENV/bin/python" -m dealfinder run --port "$PORT" >>"$LOG" 2>&1 &
  for _ in $(seq 1 60); do
    if is_current; then return 0; fi
    sleep 0.5
  done
  return 1
}
if start_new; then open "$URL"; exit 0; fi
# Something else answered (an old copy came back) or it didn't start: clear the port and try once more.
port_in_use && stop_old
if start_new; then open "$URL"; exit 0; fi
fail "it didn't start. Restart your Mac, then open Deal Finder again."
