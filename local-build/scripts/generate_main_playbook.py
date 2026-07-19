#!/usr/bin/env python3
"""Generate a main-only Antora playbook from docs-config derived version."""

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
        print("Usage: generate_main_playbook.py <source_playbook> <target_playbook> <main_version>")
        return 2

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
