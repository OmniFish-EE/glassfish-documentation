#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/build/site"
PORT="5000"
WATCH_MODE="false"
WATCH_SCOPE="main"

for arg in "$@"; do
  case "$arg" in
    --watch)
      WATCH_MODE="true"
      ;;
    --all)
      WATCH_SCOPE="all"
      ;;
    *)
      if [[ "$arg" =~ ^[0-9]+$ ]]; then
        PORT="$arg"
      else
        echo "Unsupported argument: $arg"
        echo "Usage: local-build/serve-site.sh [PORT] [--watch] [--all]"
        exit 1
      fi
      ;;
  esac
done

resolve_main_version() {
  awk '
    $1 == "-" && $2 == "version:" {
      v = $3
      gsub(/"/, "", v)
    }
    $1 == "ref:" && $2 == "main" {
      print v
      exit
    }
  ' "$ROOT_DIR/docs-config.yml"
}

PLAYBOOK_FILE="$ROOT_DIR/antora-playbook.yml"

generate_main_playbook() {
  local main_version="$1"
  local source_playbook="$ROOT_DIR/antora-playbook.yml"
  local target_playbook="$ROOT_DIR/.antora-playbook.main.yml"

  python3 - "$source_playbook" "$target_playbook" "$main_version" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"], check=True)
    import yaml

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
main_version = sys.argv[3]

data = yaml.safe_load(src.read_text(encoding="utf-8"))
sources = data.get("content", {}).get("sources", [])
filtered = [s for s in sources if str(s.get("start_path", "")) == main_version]

if not filtered:
    raise SystemExit(f"No content.sources entry found for main version: {main_version}")

data["content"]["sources"] = filtered
dst.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY

  PLAYBOOK_FILE="$target_playbook"
}

WATCH_PID=""

cleanup() {
  if [[ -n "$WATCH_PID" ]] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if [[ "$WATCH_MODE" == "true" ]]; then
  if [[ "$WATCH_SCOPE" == "main" ]]; then
    MAIN_VERSION="$(resolve_main_version)"
    if [[ -z "$MAIN_VERSION" ]]; then
      echo "Could not resolve main version from docs-config.yml"
      exit 1
    fi
    generate_main_playbook "$MAIN_VERSION"
  else
    PLAYBOOK_FILE="$ROOT_DIR/antora-playbook.yml"
  fi

  echo "Preparing initial build before watch mode"
  if [[ "$WATCH_SCOPE" == "all" ]]; then
    echo "Watch scope: all versions"
    bash "$ROOT_DIR/local-build/build-site.sh" --all
  else
    echo "Watch scope: main branch only"
    bash "$ROOT_DIR/local-build/build-site.sh" --main
  fi

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

  ensure_scope_playbook() {
    if [[ "$WATCH_SCOPE" == "main" && ! -f "$PLAYBOOK_FILE" ]]; then
      echo "Main-scope playbook missing; regenerating..."
      generate_main_playbook "$MAIN_VERSION"
    fi
  }

  run_antora_build() {
    cd "$ROOT_DIR"
    ensure_scope_playbook
    "$ANTORA_CMD" "$PLAYBOOK_FILE" --to-dir build/site
  }

  run_transform() {
    cd "$ROOT_DIR"
    if [[ "$WATCH_SCOPE" == "all" ]]; then
      python3 build_antora_content.py
    else
      # Remove stale generated versions so watch mode stays main-only.
      if [[ -d "$ROOT_DIR/antora-content" ]]; then
        find "$ROOT_DIR/antora-content" -mindepth 1 -maxdepth 1 -type d ! -name "$MAIN_VERSION" -exec rm -rf {} +
      fi

      python3 build_antora_content.py "$MAIN_VERSION"
      generate_main_playbook "$MAIN_VERSION"
    fi
  }

  full_rebuild() {
    cd "$ROOT_DIR"
    echo "Running full rebuild (transform + site build)..."
    if run_transform && run_antora_build; then
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

  classify_rebuild_mode() {
    local changed_path="$1"

    case "$changed_path" in
      supplemental-ui/*|antora-playbook.yml|antora-content/*)
        echo "fast"
        ;;
      glassfish-repo/docs/*|build_antora_content.py|docs-config.yml)
        echo "full"
        ;;
      *)
        echo "full"
        ;;
    esac
  }

  run_pending_rebuild() {
    local pending_mode="$1"

    if [[ "$pending_mode" == "full" ]]; then
      full_rebuild
    elif [[ "$pending_mode" == "fast" ]]; then
      fast_rebuild
    fi
  }

  watch_loop() {
    cd "$ROOT_DIR"
    echo "Watching for changes and rebuilding after 5s of inactivity..."

    local pending_mode="none"
    local changed_file
    local mode
    local rebuild_pid=""
    local rebuild_mode="none"
    local last_change_epoch="0"
    local now_epoch

    coproc INOTIFY_STREAM {
      inotifywait -m -r -e modify,create,delete,move \
        --format '%w%f' \
        "$ROOT_DIR/supplemental-ui" \
        "$ROOT_DIR/glassfish-repo/docs" \
        "$ROOT_DIR/antora-content" \
        "$ROOT_DIR/antora-playbook.yml" \
        "$ROOT_DIR/docs-config.yml" \
        "$ROOT_DIR/build_antora_content.py" 2>/dev/null
    }

    while true; do
      if read -t 1 -r changed_file <&"${INOTIFY_STREAM[0]}"; then
        changed_file="${changed_file#$ROOT_DIR/}"
        changed_file="${changed_file#./}"
        echo "Detected change: $changed_file"

        mode="$(classify_rebuild_mode "$changed_file")"
        if [[ "$mode" == "full" ]]; then
          pending_mode="full"
        elif [[ "$pending_mode" == "none" ]]; then
          pending_mode="fast"
        fi

        last_change_epoch="$(date +%s)"

        if [[ -n "$rebuild_pid" ]] && kill -0 "$rebuild_pid" 2>/dev/null; then
          echo "Change detected during $rebuild_mode rebuild; stopping and waiting for quiet period..."
          kill "$rebuild_pid" 2>/dev/null || true
          wait "$rebuild_pid" 2>/dev/null || true
          rebuild_pid=""
          rebuild_mode="none"
        fi
      fi

      if [[ -n "$rebuild_pid" ]] && ! kill -0 "$rebuild_pid" 2>/dev/null; then
        wait "$rebuild_pid" 2>/dev/null || true
        rebuild_pid=""
        rebuild_mode="none"
      fi

      if [[ "$pending_mode" != "none" && -z "$rebuild_pid" && "$last_change_epoch" -gt 0 ]]; then
        now_epoch="$(date +%s)"
        if (( now_epoch - last_change_epoch >= 5 )); then
          echo "No changes for 5 seconds. Starting $pending_mode rebuild..."
          rebuild_mode="$pending_mode"
          pending_mode="none"
          last_change_epoch="0"
          (
            run_pending_rebuild "$rebuild_mode"
          ) &
          rebuild_pid="$!"
        fi
      fi
    done
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
