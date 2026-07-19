#!/usr/bin/env python3
"""Prepare a temp playbook that points to temp content/UI artifacts."""

from pathlib import Path
import subprocess
import sys

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"], check=True)
    import yaml


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: prepare_temp_playbook.py <source_playbook> <temp_playbook> <temp_content_repo>")
        return 2

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    temp_repo = Path(sys.argv[3])

    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    sources = data.get("content", {}).get("sources", [])
    for source in sources:
        if str(source.get("url", "")) == "./antora-content":
            source["url"] = f"./{temp_repo.name}"

    ui = data.get("ui", {})
    bundle = ui.get("bundle", {})
    if isinstance(bundle.get("url"), str):
        bundle["url"] = "./antora-ui-default.zip"

    if isinstance(ui.get("supplemental_files"), str):
        ui["supplemental_files"] = "./supplemental-ui"

    dst.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
