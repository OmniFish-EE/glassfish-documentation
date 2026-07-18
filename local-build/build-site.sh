#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

echo "[4/5] Initializing Antora content git repository"
mkdir -p antora-content
cd antora-content
if [[ ! -d .git ]]; then
  git init
fi
git config user.email "actions@github.com"
git config user.name "GitHub Actions"
git add -A
if git diff --cached --quiet; then
  echo "No content changes to commit"
else
  git commit -m "Generated content"
fi
cd "$ROOT_DIR"

echo "[5/5] Building Antora site"
"$ANTORA_CMD" "$PLAYBOOK_FILE" --to-dir build/site

echo "Build completed: $ROOT_DIR/build/site"

