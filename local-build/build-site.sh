#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_DIR="$ROOT_DIR/temp"
cd "$ROOT_DIR"

BUILD_SCOPE="all"
for arg in "$@"; do
  case "$arg" in
    --all)
      BUILD_SCOPE="all"
      ;;
    --main)
      BUILD_SCOPE="main"
      ;;
    *)
      echo "Unsupported argument: $arg"
      echo "Usage: local-build/build-site.sh [--main|--all]"
      exit 1
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
TEMP_CONTENT_REPO_DIR="$TEMP_DIR/antora-content-tmp"
TEMP_PLAYBOOK_FILE="$TEMP_DIR/antora-playbook.tmp.yml"
TEMP_UI_BUNDLE_FILE="$TEMP_DIR/antora-ui-default.zip"
TEMP_SUPPLEMENTAL_DIR="$TEMP_DIR/supplemental-ui"

generate_main_playbook() {
  local main_version="$1"
  local source_playbook="$ROOT_DIR/antora-playbook.yml"
  mkdir -p "$TEMP_DIR"
  local target_playbook="$TEMP_DIR/antora-playbook.main.yml"

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

cleanup_temp_artifacts() {
  if [[ -f "$TEMP_PLAYBOOK_FILE" ]]; then
    rm -f "$TEMP_PLAYBOOK_FILE"
  fi
  if [[ -d "$TEMP_CONTENT_REPO_DIR" ]]; then
    rm -rf "$TEMP_CONTENT_REPO_DIR"
  fi
  if [[ -f "$TEMP_UI_BUNDLE_FILE" ]]; then
    rm -f "$TEMP_UI_BUNDLE_FILE"
  fi
  if [[ -d "$TEMP_SUPPLEMENTAL_DIR" ]]; then
    rm -rf "$TEMP_SUPPLEMENTAL_DIR"
  fi
}

trap cleanup_temp_artifacts EXIT INT TERM

prepare_temp_content_repo() {
  local source_dir="$ROOT_DIR/antora-content"
  if [[ ! -d "$source_dir" ]]; then
    echo "Antora content directory not found: $source_dir"
    exit 1
  fi

  mkdir -p "$TEMP_DIR"

  rm -rf "$TEMP_CONTENT_REPO_DIR"
  mkdir -p "$TEMP_CONTENT_REPO_DIR"
  cp -a "$source_dir/." "$TEMP_CONTENT_REPO_DIR/"

  git -C "$TEMP_CONTENT_REPO_DIR" init -q
  git -C "$TEMP_CONTENT_REPO_DIR" config user.email "actions@github.com"
  git -C "$TEMP_CONTENT_REPO_DIR" config user.name "GitHub Actions"
  git -C "$TEMP_CONTENT_REPO_DIR" add -A
  if git -C "$TEMP_CONTENT_REPO_DIR" diff --cached --quiet; then
    git -C "$TEMP_CONTENT_REPO_DIR" commit --allow-empty -m "Generated content" >/dev/null 2>&1
  else
    git -C "$TEMP_CONTENT_REPO_DIR" commit -m "Generated content" >/dev/null 2>&1
  fi
}

prepare_temp_playbook() {
  local source_playbook="$PLAYBOOK_FILE"
  local source_ui_bundle="$ROOT_DIR/antora-ui-default.zip"
  local source_supplemental_dir="$ROOT_DIR/supplemental-ui"
  mkdir -p "$TEMP_DIR"
  rm -f "$TEMP_PLAYBOOK_FILE"
  rm -f "$TEMP_UI_BUNDLE_FILE"
  rm -rf "$TEMP_SUPPLEMENTAL_DIR"

  cp "$source_ui_bundle" "$TEMP_UI_BUNDLE_FILE"
  cp -a "$source_supplemental_dir" "$TEMP_SUPPLEMENTAL_DIR"

  python3 - "$source_playbook" "$TEMP_PLAYBOOK_FILE" "$TEMP_CONTENT_REPO_DIR" <<'PY'
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
temp_repo = sys.argv[3]

data = yaml.safe_load(src.read_text(encoding="utf-8"))
sources = data.get("content", {}).get("sources", [])
for source in sources:
    if str(source.get("url", "")) == "./antora-content":
        source["url"] = f"./{Path(temp_repo).name}"

ui = data.get("ui", {})
bundle = ui.get("bundle", {})
if isinstance(bundle.get("url"), str):
    bundle["url"] = "./antora-ui-default.zip"

if isinstance(ui.get("supplemental_files"), str):
    ui["supplemental_files"] = "./supplemental-ui"

dst.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY
}

NPM_GLOBAL_BIN="$(npm prefix -g)/bin"
if [[ -d "$NPM_GLOBAL_BIN" ]]; then
  export PATH="$NPM_GLOBAL_BIN:$PATH"
fi

if command -v antora >/dev/null 2>&1; then
  echo "[1/5] Antora already installed, skipping"
  ANTORA_CMD="$(command -v antora)"
else
  echo "[1/5] Installing Antora tooling"
  npm install -g @antora/cli@3.1 @antora/site-generator@3.1 @antora/lunr-extension
  if command -v antora >/dev/null 2>&1; then
    ANTORA_CMD="$(command -v antora)"
  else
    echo "Antora executable not found after npm install."
    echo "Expected in: $NPM_GLOBAL_BIN"
    exit 1
  fi
fi

echo "[2/5] Preparing upstream GlassFish docs checkout"
if [[ ! -d glassfish-repo/.git ]]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/eclipse-ee4j/glassfish.git glassfish-repo
  cd glassfish-repo
  git sparse-checkout set docs
  cd "$ROOT_DIR"
else
  cd glassfish-repo
  git sparse-checkout init --cone
  git sparse-checkout set docs
  git fetch --depth 1 origin main
  if git show-ref --verify --quiet refs/heads/main; then
    git checkout main
  else
    git checkout -b main origin/main
  fi
  git reset --hard origin/main
  cd "$ROOT_DIR"
fi

echo "[3/5] Transforming sources for Antora (includes xref fixes)"
if [[ "$BUILD_SCOPE" == "main" ]]; then
  MAIN_VERSION="$(resolve_main_version)"
  if [[ -z "$MAIN_VERSION" ]]; then
    echo "Could not resolve main version from docs-config.yml"
    exit 1
  fi
  echo "Building main branch version only: $MAIN_VERSION"

  # Remove stale generated versions so Antora output contains only main branch docs.
  if [[ -d "$ROOT_DIR/antora-content" ]]; then
    find "$ROOT_DIR/antora-content" -mindepth 1 -maxdepth 1 -type d ! -name "$MAIN_VERSION" -exec rm -rf {} +
  fi

  python3 build_antora_content.py "$MAIN_VERSION"
  generate_main_playbook "$MAIN_VERSION"
else
  echo "Building all configured versions"
  python3 build_antora_content.py
fi

echo "[4/5] Preparing temporary Antora content git repository"
prepare_temp_content_repo
prepare_temp_playbook

echo "[5/5] Building Antora site"
"$ANTORA_CMD" "$TEMP_PLAYBOOK_FILE" --to-dir build/site

echo "Build completed: $ROOT_DIR/build/site"

