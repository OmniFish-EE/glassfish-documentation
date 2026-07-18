#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/build/site"
PORT="5000"
WATCH_MODE="false"

for arg in "$@"; do
  case "$arg" in
    --watch)
      WATCH_MODE="true"
      ;;
    *)
      if [[ "$arg" =~ ^[0-9]+$ ]]; then
        PORT="$arg"
      else
        echo "Unsupported argument: $arg"
        echo "Usage: local-build/serve-site.sh [PORT] [--watch]"
        exit 1
      fi
      ;;
  esac
done

WATCH_PID=""

cleanup() {
  if [[ -n "$WATCH_PID" ]] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if [[ "$WATCH_MODE" == "true" ]]; then
  echo "Preparing initial build before watch mode"
  bash "$ROOT_DIR/local-build/build-site.sh"

  NPM_GLOBAL_BIN="$(npm prefix -g)/bin"
  if [[ -d "$NPM_GLOBAL_BIN" ]]; then
    export PATH="$NPM_GLOBAL_BIN:$PATH"
  fi
  if command -v antora >/dev/null 2>&1; then
    ANTORA_CMD="$(command -v antora)"
  else
    echo "Antora not found, installing..."
    npm install -g @antora/cli@3.1 @antora/site-generator@3.1 @antora/lunr-extension
    if command -v antora >/dev/null 2>&1; then
      ANTORA_CMD="$(command -v antora)"
    else
      echo "Antora executable not found after npm install."
      echo "Expected in: $NPM_GLOBAL_BIN"
      exit 1
    fi
  fi

  if ! command -v inotifywait >/dev/null 2>&1; then
    echo "Watch mode requires inotifywait (inotify-tools package)."
    echo "Install it, then rerun with --watch."
    exit 1
  fi

  run_antora_build() {
    cd "$ROOT_DIR"
    "$ANTORA_CMD" antora-playbook.yml --to-dir build/site
  }

  full_rebuild() {
    cd "$ROOT_DIR"
    echo "Running full rebuild (transform + site build)..."
    if python3 build_antora_content.py && run_antora_build; then
      echo "Full rebuild completed."
    else
      echo "Full rebuild failed; keeping server running for current output."
    fi
  }

  fast_rebuild() {
    cd "$ROOT_DIR"
    echo "Running fast rebuild (site build only)..."
    if run_antora_build; then
      echo "Fast rebuild completed."
    else
      echo "Fast rebuild failed; keeping server running for current output."
    fi
  }

  rebuild_on_change() {
    local changed_path="$1"

    case "$changed_path" in
      supplemental-ui/*|antora-playbook.yml|antora-content/*)
        fast_rebuild
        ;;
      glassfish-repo/docs/*|build_antora_content.py|docs-config.yml)
        full_rebuild
        ;;
      *)
        echo "Change detected in $changed_path; running full rebuild for safety."
        full_rebuild
        ;;
    esac
  }

  watch_loop() {
    cd "$ROOT_DIR"
    echo "Watching for changes and selecting fast/full rebuild automatically..."
    while IFS= read -r changed_file; do
      changed_file="${changed_file#$ROOT_DIR/}"
      changed_file="${changed_file#./}"
      echo "Detected change: $changed_file"
      rebuild_on_change "$changed_file"
    done < <(
      inotifywait -m -r -e modify,create,delete,move \
        --format '%w%f' \
        "$ROOT_DIR/supplemental-ui" \
        "$ROOT_DIR/glassfish-repo/docs" \
        "$ROOT_DIR/antora-content" \
        "$ROOT_DIR/antora-playbook.yml" \
        "$ROOT_DIR/docs-config.yml" \
        "$ROOT_DIR/build_antora_content.py"
    )
  }

  ensure_antora_content() {
    if [[ ! -d "$ROOT_DIR/antora-content" ]]; then
      mkdir -p "$ROOT_DIR/antora-content"
    fi
  }

  echo "Starting local file watch mode (auto-rebuild on changes)"
  cd "$ROOT_DIR"
  ensure_antora_content
  watch_loop &
  WATCH_PID="$!"
elif [[ ! -d "$SITE_DIR" ]]; then
  echo "Site directory not found: $SITE_DIR"
  echo "Run local-build/build-site.sh first, or run with --watch to build automatically."
  exit 1
fi

cd "$SITE_DIR"
echo "Serving Antora site at http://localhost:$PORT"
python3 -m http.server "$PORT"
