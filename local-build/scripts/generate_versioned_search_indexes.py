#!/usr/bin/env python3
"""Generate one Lunr search index file per Antora content version.

This script creates one temporary playbook per version, runs Antora for each,
and copies the generated ``search-index.js`` into the main output directory as
``search-index-<version>.js``.
"""

from pathlib import Path
import re
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"], check=True)
    import yaml


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid YAML object in playbook: {path}")
    return data


def _collect_versions(playbook: dict) -> list[str]:
    versions: list[str] = []
    seen: set[str] = set()
    for source in playbook.get("content", {}).get("sources", []):
        version = str(source.get("start_path", "")).strip()
        if not version or version in seen:
            continue
        versions.append(version)
        seen.add(version)
    return versions


def _find_version_for_segment(index_path: Path, versions: list[str], segment: str) -> str | None:
    if not index_path.is_file():
        return None

    index_data = index_path.read_text(encoding="utf-8")
    for version in versions:
        document_url = re.compile(
            rf'"version":"{re.escape(version)}","name":"[^"]+",'
            rf'"url":"/[^"]+/{re.escape(segment)}/'
        )
        if document_url.search(index_data):
            return version
    return None


def _write_versioned_index(
    source: Path, target: Path, version: str, url_segment: str
) -> None:
    index_data = source.read_text(encoding="utf-8")
    index_data = re.sub(
        rf'("url":"/[^"/]+/)(?:latest|{re.escape(version)})/',
        lambda match: f"{match.group(1)}{url_segment}/",
        index_data,
    )
    target.write_text(index_data, encoding="utf-8")


def _build_single_version(
    antora_cmd: str,
    base_playbook: dict,
    version: str,
    output_site_dir: Path,
    work_dir: Path,
    playbook_dir: Path,
    url_segment: str,
) -> None:
    sources = base_playbook.get("content", {}).get("sources", [])
    filtered = [s for s in sources if str(s.get("start_path", "")).strip() == version]
    if not filtered:
        raise SystemExit(f"No content source found for version: {version}")

    version_playbook = dict(base_playbook)
    version_content = dict(version_playbook.get("content", {}))
    normalized_sources = []
    for source in filtered:
        if isinstance(source, dict):
            source_copy = dict(source)
            source_url = source_copy.get("url", "")
            if source_url and not source_url.startswith(("http://", "https://", "/")) and not source_url.startswith("git@"):
                source_copy["url"] = str((playbook_dir / source_url).resolve())
            normalized_sources.append(source_copy)
        else:
            normalized_sources.append(source)
    version_content["sources"] = normalized_sources
    version_playbook["content"] = version_content

    # A single-version build would otherwise treat every version as the latest
    # version and write /latest/ URLs into each generated search index.
    version_urls = dict(version_playbook.get("urls", {}))
    version_urls.pop("latest_version_segment", None)
    version_urls.pop("latest_version_segment_strategy", None)
    version_playbook["urls"] = version_urls

    if "ui" in version_playbook and isinstance(version_playbook["ui"], dict):
        if "bundle" in version_playbook["ui"]:
            bundle_url = version_playbook["ui"]["bundle"].get("url", "")
            if bundle_url and not bundle_url.startswith(("http://", "https://", "/")):
                version_playbook["ui"]["bundle"]["url"] = str((playbook_dir / bundle_url).resolve())
        if "supplemental_files" in version_playbook["ui"]:
            supp_dir = version_playbook["ui"]["supplemental_files"]
            if supp_dir and not supp_dir.startswith("/"):
                version_playbook["ui"]["supplemental_files"] = str((playbook_dir / supp_dir).resolve())

    playbook_path = work_dir / f"antora-playbook.{version}.yml"
    version_out_dir = work_dir / f"site-{version}"
    playbook_path.write_text(yaml.safe_dump(version_playbook, sort_keys=False), encoding="utf-8")

    subprocess.run(
        [antora_cmd, str(playbook_path), "--to-dir", str(version_out_dir)],
        check=True,
        cwd=str(playbook_dir),
    )

    source_index = version_out_dir / "search-index.js"
    if not source_index.is_file():
        raise SystemExit(f"Expected search index not found: {source_index}")

    target_index = output_site_dir / f"search-index-{version}.js"
    _write_versioned_index(source_index, target_index, version, url_segment)


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: generate_versioned_search_indexes.py <base_playbook> <output_site_dir> <antora_cmd>"
        )
        return 2

    base_playbook_path = Path(sys.argv[1]).resolve()
    output_site_dir = Path(sys.argv[2]).resolve()
    antora_cmd = sys.argv[3]

    if not base_playbook_path.is_file():
        raise SystemExit(f"Playbook file not found: {base_playbook_path}")
    if not output_site_dir.is_dir():
        raise SystemExit(f"Output site directory not found: {output_site_dir}")

    playbook = _load_yaml(base_playbook_path)
    versions = _collect_versions(playbook)

    if not versions:
        raise SystemExit("No versions found in playbook content.sources")

    latest_segment = str(playbook.get("urls", {}).get("latest_version_segment", "")).strip()
    latest_version = (
        _find_version_for_segment(output_site_dir / "search-index.js", versions, latest_segment)
        if latest_segment
        else None
    )
    if latest_segment and latest_version is None:
        raise SystemExit(
            f"Could not determine which version uses the {latest_segment!r} URL segment "
            f"from {output_site_dir / 'search-index.js'}"
        )
    if latest_version:
        print(f"Version {latest_version} uses the {latest_segment!r} URL segment")

    with tempfile.TemporaryDirectory(prefix="versioned-search-") as tmp:
        work_dir = Path(tmp)
        for version in versions:
            print(f"Generating search index for version: {version}")
            url_segment = latest_segment if version == latest_version else version
            _build_single_version(
                antora_cmd,
                playbook,
                version,
                output_site_dir,
                work_dir,
                base_playbook_path.parent,
                url_segment,
            )

    print(f"Generated {len(versions)} versioned search indexes in {output_site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
