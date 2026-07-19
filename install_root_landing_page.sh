#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_TEMPLATE="${2:-$ROOT_DIR/templates/root-index.html}"
TARGET_SITE_DIR="${1:-$ROOT_DIR/build/site}"
TARGET_INDEX="$TARGET_SITE_DIR/index.html"

if [[ ! -f "$SOURCE_TEMPLATE" ]]; then
  echo "Root landing page template missing: $SOURCE_TEMPLATE"
  exit 1
fi

mkdir -p "$TARGET_SITE_DIR"
cp "$SOURCE_TEMPLATE" "$TARGET_INDEX"
