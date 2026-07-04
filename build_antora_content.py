#!/usr/bin/env python3
"""
Transform GlassFish Maven/JBake adoc sources into an Antora content source.

Each Maven module (guide) becomes an Antora module under a single component.
The JBake-style header (key=value lines before ~~~~~~) is stripped.
A nav.adoc is generated for each guide from the next= chain.
An antora.yml is created at the component root.

Configuration is loaded from docs-config.yml in the same directory.

Usage:
  python3 build_antora_content.py                    # builds all versions
  python3 build_antora_content.py 8.0-SNAPSHOT       # builds one version
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"], check=True)
    import yaml

# Resolve paths relative to this script's location (repo root)
REPO_ROOT = Path(__file__).parent

# ── Load configuration ─────────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = REPO_ROOT / "docs-config.yml"
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

CONFIG = load_config()

VERSIONS = [
    (
        v["version"],
        v["ref"],
        str(v["major"]),
        str(v["jakartaee"]),
        v["display"],
        bool(v.get("prerelease", False)),
    )
    for v in CONFIG["versions"]
]

LATEST_VERSION: str = CONFIG["latest_version"]

GUIDES: list[tuple[str, str]] = [
    (g["dir"], g["title"]) for g in CONFIG["guides"]
]

# Files to skip (index/list pages not useful as standalone pages)
SKIP_FILES = {"book.adoc", "loe.adoc", "lof.adoc", "lot.adoc"}

ATTR_SEPARATOR = "~~~~~~"


# ── Parsing helpers ────────────────────────────────────────────────────────────

def parse_jbake_header(content: str) -> tuple[dict, str]:
    """Parse the JBake-style header and return (metadata_dict, body)."""
    lines = content.split("\n")
    meta = {}
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == ATTR_SEPARATOR:
            body_start = i + 1
            break
        if "=" in line:
            key, _, val = line.partition("=")
            meta[key.strip()] = val.strip()
    body = "\n".join(lines[body_start:])
    return meta, body


def get_page_order(guide_dir: Path) -> list[str]:
    """
    Walk the next= chain starting from title.adoc (or release-notes.adoc as
    fallback) to get the ordered page list.
    """
    adoc_files = {f.name: f for f in guide_dir.glob("*.adoc")}

    # Build next map
    next_map = {}
    for fname, fpath in adoc_files.items():
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            meta, _ = parse_jbake_header(content)
            nxt = meta.get("next", "")
            if nxt:
                nxt = re.sub(r"\.html$", ".adoc", nxt)
                next_map[fname] = nxt
        except Exception:
            pass

    # Determine start file: prefer title.adoc, fall back to release-notes.adoc
    start = "title.adoc" if "title.adoc" in adoc_files else next(
        (f for f in adoc_files if f not in SKIP_FILES), None
    )

    ordered = []
    seen = set()
    current = start
    while current and current in adoc_files and current not in seen:
        seen.add(current)
        ordered.append(current)
        current = next_map.get(current, "")

    # Add any files not reached by the chain
    for fname in sorted(adoc_files.keys()):
        if fname not in seen:
            ordered.append(fname)

    return ordered


def generate_nav_entries(guide_dir: Path, ordered_files: list[str], module_name: str, header_page: str) -> list[str]:
    """Generate nav.adoc list entries for a guide, with sub-pages nested under the guide title."""
    entries = []
    for fname in ordered_files:
        if fname in SKIP_FILES:
            continue
        fpath = guide_dir / fname
        if not fpath.exists():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            meta, _ = parse_jbake_header(content)
            title = meta.get("title", fname.replace(".adoc", "").replace("-", " ").title())
            title = re.sub(r"\{[^}]+\}", "GlassFish", title)
        except Exception:
            title = fname.replace(".adoc", "")
        # Guide title page is level 1 (*), all other pages are nested (**)
        level = "*" if fname == header_page else "**"
        entries.append(f"{level} xref:{module_name}:{fname}[{title}]")
    return entries


def process_adoc_body(body: str) -> str:
    """Fix xref links that use .html extension."""
    body = re.sub(
        r"xref:([^[#\s]+)\.html(#[^[\s]*)?\[",
        lambda m: f"xref:{m.group(1)}.adoc{m.group(2) or ''}[",
        body,
    )
    return body


# ── Per-guide module builder ───────────────────────────────────────────────────

def setup_guide_module(src_docs_dir: Path, out_root: Path, guide_name: str, display_name: str) -> str | None:
    """Set up one Antora module for a guide. Returns module_name or None."""
    src_dir = src_docs_dir / guide_name / "src" / "main" / "asciidoc"
    if not src_dir.exists():
        print(f"  SKIP {guide_name}: no src dir")
        return None

    module_name = guide_name
    module_dir = out_root / "modules" / module_name
    pages_dir = module_dir / "pages"
    images_dir = module_dir / "images"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Copy images
    img_src = src_dir / "img"
    if img_src.exists():
        if images_dir.exists():
            shutil.rmtree(images_dir)
        shutil.copytree(img_src, images_dir)

    ordered = get_page_order(src_dir)

    for fname in ordered:
        if fname in SKIP_FILES:
            continue
        fpath = src_dir / fname
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        _, body = parse_jbake_header(content)
        body = process_adoc_body(body)
        (pages_dir / fname).write_text(body, encoding="utf-8")

    # Determine the nav header page (title.adoc or first real page)
    header_page = "title.adoc" if (pages_dir / "title.adoc").exists() else ordered[0] if ordered else "title.adoc"

    nav_entries = generate_nav_entries(src_dir, ordered, module_name, header_page)
    # The first entry is the guide title at level 1 with the display name
    nav_content = f"* xref:{module_name}:{header_page}[{display_name}]\n"
    for entry in nav_entries:
        # Skip the header page entry (already written as the guide title above)
        if entry.startswith("* ") and f":{header_page}[" in entry:
            continue
        nav_content += entry + "\n"

    (module_dir / "nav.adoc").write_text(nav_content, encoding="utf-8")

    page_count = len([f for f in ordered if f not in SKIP_FILES and (src_dir / f).exists()])
    print(f"  OK  {guide_name}: {page_count} pages")
    return module_name


# ── Index page builder ─────────────────────────────────────────────────────────

def build_index_page(modules: list[tuple[str, str]], release_notes_entry: str) -> str:
    """Generate the landing index.adoc content."""
    return f"""= Eclipse GlassFish Documentation
:description: Eclipse GlassFish is a full Jakarta EE application server.

Welcome to the Eclipse GlassFish documentation.
Select a guide from the navigation panel on the left, or use the search box to find what you need.

== Developer Guides

* xref:quick-start-guide:title.adoc[Quick Start Guide] — Get GlassFish running and deploy your first application.
* xref:application-development-guide:title.adoc[Application Development Guide] — Develop Jakarta EE applications for GlassFish.
* xref:application-deployment-guide:title.adoc[Application Deployment Guide] — Deploy and manage applications.
* xref:embedded-server-guide:title.adoc[Embedded Server Guide] — Embed GlassFish in your application or tests.
* xref:add-on-component-development-guide:title.adoc[Add-On Component Development Guide] — Extend GlassFish with custom components.

== Administration Guides

* xref:administration-guide:title.adoc[Administration Guide] — Configure and administer GlassFish.
* xref:installation-guide:title.adoc[Installation Guide] — Install GlassFish on your platform.
* xref:security-guide:title.adoc[Security Guide] — Secure your GlassFish installation and applications.
* xref:ha-administration-guide:title.adoc[High Availability Administration Guide] — Set up clustering and high availability.
* xref:upgrade-guide:title.adoc[Upgrade Guide] — Upgrade from an earlier version.
* xref:troubleshooting-guide:title.adoc[Troubleshooting Guide] — Diagnose and fix common issues.

== Architecture and Planning

* xref:deployment-planning-guide:title.adoc[Deployment Planning Guide] — Plan your GlassFish deployment topology.
* xref:performance-tuning-guide:title.adoc[Performance Tuning Guide] — Tune GlassFish for production workloads.

== Reference

* xref:reference-manual:title.adoc[Reference Manual] — Complete reference for all asadmin subcommands.
* xref:error-messages-reference:title.adoc[Error Messages Reference] — Descriptions and solutions for error messages.
* {release_notes_entry}
"""


# ── Per-version builder ────────────────────────────────────────────────────────

def build_version(antora_version: str, git_ref: str, major_version: str,
                  jakartaee: str, display_label: str, is_prerelease: bool,
                  src_docs_dir: Path):
    """Build the Antora content source for one version."""
    out_root = REPO_ROOT / "antora-content" / antora_version
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    print(f"\n=== Building version {antora_version} (ref: {git_ref}) ===")

    status = "SNAPSHOT" if is_prerelease else "Final"

    prerelease_line = "prerelease: true\n" if is_prerelease else ""
    antora_yml_header = f"""name: glassfish
title: Eclipse GlassFish Documentation
version: '{antora_version}'
display_version: '{display_label}'
{prerelease_line}asciidoc:
  attributes:
    productName: Eclipse GlassFish
    product-majorVersion: '{major_version}'
    jakartaee: '{jakartaee}'
    status: {status}
nav:
  - modules/ROOT/nav.adoc
"""

    modules = []
    for guide_name, display_name in GUIDES:
        module_name = setup_guide_module(src_docs_dir, out_root, guide_name, display_name)
        if module_name:
            modules.append((module_name, display_name))

    # Add nav entries
    nav_lines = "".join(f"  - modules/{m}/nav.adoc\n" for m, _ in modules)
    antora_yml = antora_yml_header + nav_lines

    (out_root / "antora.yml").write_text(antora_yml, encoding="utf-8")

    # ROOT module
    root_pages = out_root / "modules" / "ROOT" / "pages"
    root_pages.mkdir(parents=True, exist_ok=True)

    # Determine release-notes entry (7.x uses release-notes.adoc, 8.x uses title.adoc)
    rn_src = src_docs_dir / "release-notes" / "src" / "main" / "asciidoc"
    if (rn_src / "title.adoc").exists():
        rn_entry = "xref:release-notes:title.adoc[Release Notes] — What's new and changed in this release."
    else:
        rn_entry = "xref:release-notes:release-notes.adoc[Release Notes] — What's new and changed in this release."

    index_content = build_index_page(modules, rn_entry)
    (root_pages / "index.adoc").write_text(index_content, encoding="utf-8")
    (out_root / "modules" / "ROOT" / "nav.adoc").write_text(
        "* xref:ROOT:index.adoc[Home]\n", encoding="utf-8"
    )

    print(f"  Done: {len(modules)} guides written to {out_root}")
    return out_root


# ── Checkout helper ────────────────────────────────────────────────────────────

def get_docs_dir(git_ref: str) -> Path:
    """
    Return the path to the docs directory for a given git ref.
    For 'main' we use the already-checked-out sparse clone.
    For tags we do a separate sparse checkout into a temp directory.
    """
    repo_dir = REPO_ROOT / "glassfish-repo"

    if git_ref == "main":
        return repo_dir / "docs"

    # For tags: checkout into a worktree or temp clone
    tag_dir = REPO_ROOT / "glassfish-repo-tags" / git_ref
    if tag_dir.exists():
        return tag_dir / "docs"

    tag_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Fetching tag {git_ref} from upstream...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
         "--branch", git_ref,
         "https://github.com/eclipse-ee4j/glassfish.git", str(tag_dir)],
        check=True, capture_output=True
    )
    subprocess.run(
        ["git", "sparse-checkout", "set", "docs"],
        cwd=tag_dir, check=True, capture_output=True
    )
    return tag_dir / "docs"


# ── Fix xrefs ─────────────────────────────────────────────────────────────────

def fix_xrefs_in_version(out_root: Path):
    """Fix cross-guide xref links in all modules of a version."""
    modules_dir = out_root / "modules"
    if not modules_dir.exists():
        return

    module_names = {d.name for d in modules_dir.iterdir() if d.is_dir() and d.name != "ROOT"}
    module_pages = {
        m: {f.name for f in (modules_dir / m / "pages").glob("*.adoc")}
        for m in module_names
        if (modules_dir / m / "pages").exists()
    }

    pattern = re.compile(r"xref:((?:\.\.\/)?[^[#:\s]+?)((?:#[^[\s]*)?(?:\[[^\]]*\])+)")

    def replace_xref(m, current_module):
        full_match = m.group(0)
        target = m.group(1)
        rest = m.group(2)

        if ":" in target and not target.startswith(".."):
            return full_match
        if target.startswith("../"):
            target = target[3:]

        if "#" in target:
            filename, anchor = target.split("#", 1)
            anchor = "#" + anchor
        else:
            filename = target
            anchor = ""

        filename = re.sub(r"\.html$", ".adoc", filename)
        stem = filename.replace(".adoc", "")

        if stem in module_names:
            if stem == current_module:
                return f"xref:title.adoc{anchor}{rest}"
            # Determine correct entry page for this module
            entry = "title.adoc" if "title.adoc" in module_pages.get(stem, set()) else "release-notes.adoc"
            return f"xref:{stem}:{entry}{anchor}{rest}"

        for mod_name, pages in module_pages.items():
            if mod_name != current_module and filename in pages:
                return f"xref:{mod_name}:{filename}{anchor}{rest}"

        if filename != target.split("#")[0]:
            return f"xref:{filename}{anchor}{rest}"
        return full_match

    total_fixed = 0
    for module_name in sorted(module_names):
        pages_dir = modules_dir / module_name / "pages"
        if not pages_dir.exists():
            continue
        fixed = 0
        for adoc_file in pages_dir.glob("*.adoc"):
            content = adoc_file.read_text(encoding="utf-8", errors="replace")
            original = content
            content = pattern.sub(lambda m: replace_xref(m, module_name), content)
            if content != original:
                adoc_file.write_text(content, encoding="utf-8")
                fixed += 1
        total_fixed += fixed
    print(f"  xrefs fixed in {total_fixed} files")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Allow building a single version: python3 build_antora_content.py 8.0.3
    filter_version = sys.argv[1] if len(sys.argv) > 1 else None

    versions_to_build = [
        v for v in VERSIONS
        if filter_version is None or v[0] == filter_version
    ]
    if not versions_to_build:
        print(f"Unknown version: {filter_version}")
        print(f"Available: {[v[0] for v in VERSIONS]}")
        sys.exit(1)

    for antora_version, git_ref, major_version, jakartaee, display_label, is_prerelease in versions_to_build:
        src_docs_dir = get_docs_dir(git_ref)
        out_root = build_version(
            antora_version, git_ref, major_version, jakartaee,
            display_label, is_prerelease, src_docs_dir
        )
        fix_xrefs_in_version(out_root)

    print("\nAll versions built successfully.")


if __name__ == "__main__":
    main()
