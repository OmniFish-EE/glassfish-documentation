#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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
python3 build_antora_content.py

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
"$ANTORA_CMD" antora-playbook.yml --to-dir build/site

echo "Build completed: $ROOT_DIR/build/site"

