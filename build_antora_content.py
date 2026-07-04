#!/usr/bin/env python3
"""
Transform GlassFish Maven/JBake adoc sources into an Antora content source.

Each Maven module (guide) becomes an Antora module under a single component.
The JBake-style header (key=value lines before ~~~~~~) is stripped.
A nav.adoc is generated for each guide from the next= chain.
An antora.yml is created at the component root.
"""

import os
import re
import shutil
from pathlib import Path

# Resolve paths relative to this script's location (repo root)
REPO_ROOT = Path(__file__).parent
REPO_DOCS = REPO_ROOT / "glassfish-repo" / "docs"
OUT_ROOT = REPO_ROOT / "antora-content"

# Guides to include, with display names and nav order
GUIDES = [
    ("quick-start-guide",                "Quick Start Guide"),
    ("installation-guide",               "Installation Guide"),
    ("administration-guide",             "Administration Guide"),
    ("application-development-guide",    "Application Development Guide"),
    ("application-deployment-guide",     "Application Deployment Guide"),
    ("deployment-planning-guide",        "Deployment Planning Guide"),
    ("security-guide",                   "Security Guide"),
    ("performance-tuning-guide",         "Performance Tuning Guide"),
    ("ha-administration-guide",          "High Availability Administration Guide"),
    ("troubleshooting-guide",            "Troubleshooting Guide"),
    ("reference-manual",                 "Reference Manual"),
    ("error-messages-reference",         "Error Messages Reference"),
    ("upgrade-guide",                    "Upgrade Guide"),
    ("embedded-server-guide",            "Embedded Server Guide"),
    ("add-on-component-development-guide", "Add-On Component Development Guide"),
    ("release-notes",                    "Release Notes"),
]

# Files to skip (index/list pages not useful as standalone pages)
SKIP_FILES = {"book.adoc", "loe.adoc", "lof.adoc", "lot.adoc"}

ATTR_SEPARATOR = "~~~~~~"


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
    Walk the next= chain starting from title.adoc to get ordered page list.
    Falls back to alphabetical if chain is broken.
    """
    adoc_files = {f.name: f for f in guide_dir.glob("*.adoc")}
    
    # Build next map
    next_map = {}
    for fname, fpath in adoc_files.items():
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            meta, _ = parse_jbake_header(content)
            nxt = meta.get("next", "")
            # Normalize: strip .html -> .adoc
            if nxt:
                nxt = re.sub(r"\.html$", ".adoc", nxt)
                next_map[fname] = nxt
        except Exception:
            pass

    # Walk chain from title.adoc
    ordered = []
    seen = set()
    current = "title.adoc"
    while current and current in adoc_files and current not in seen:
        seen.add(current)
        ordered.append(current)
        current = next_map.get(current, "")

    # Add any files not reached by the chain
    for fname in sorted(adoc_files.keys()):
        if fname not in seen:
            ordered.append(fname)

    return ordered


def generate_nav_entries(guide_dir: Path, ordered_files: list[str], module_name: str) -> list[str]:
    """Generate nav.adoc list entries for a guide."""
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
            # Replace attribute references with plain text
            title = re.sub(r"\{[^}]+\}", "GlassFish", title)
            page_name = fname.replace(".adoc", "")
            entries.append(f"* xref:{module_name}:{fname}[{title}]")
        except Exception:
            page_name = fname.replace(".adoc", "")
            entries.append(f"* xref:{module_name}:{fname}[{page_name}]")
    return entries


def process_adoc_body(body: str, guide_name: str) -> str:
    """
    Post-process the adoc body:
    - Replace {productName} and similar attributes
    - Fix xref links that use .html extension
    - Keep everything else as-is (Asciidoctor handles the rest)
    """
    # Fix xref links: xref:filename.html[...] -> xref:filename.adoc[...]
    body = re.sub(r"xref:([^[#\s]+)\.html(#[^[\s]*)?\[", 
                  lambda m: f"xref:{m.group(1)}.adoc{m.group(2) or ''}[", body)
    
    # Fix link: references that point to other guides
    # These will remain as external links for now
    
    return body


def setup_guide_module(guide_name: str, display_name: str):
    """Set up one Antora module for a guide."""
    src_dir = REPO_DOCS / guide_name / "src" / "main" / "asciidoc"
    if not src_dir.exists():
        print(f"  SKIP {guide_name}: no src dir")
        return None

    module_name = guide_name
    module_dir = OUT_ROOT / "modules" / module_name
    pages_dir = module_dir / "pages"
    images_dir = module_dir / "images"
    
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Copy images if present
    img_src = src_dir / "img"
    if img_src.exists():
        if images_dir.exists():
            shutil.rmtree(images_dir)
        shutil.copytree(img_src, images_dir)

    adoc_files = list(src_dir.glob("*.adoc"))
    ordered = get_page_order(src_dir)

    # Process each adoc file
    for fname in ordered:
        if fname in SKIP_FILES:
            continue
        fpath = src_dir / fname
        if not fpath.exists():
            continue
        
        content = fpath.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_jbake_header(content)
        body = process_adoc_body(body, guide_name)
        
        # Write processed file
        out_path = pages_dir / fname
        out_path.write_text(body, encoding="utf-8")

    # Generate nav.adoc
    nav_entries = generate_nav_entries(src_dir, ordered, module_name)
    nav_content = f"* xref:{module_name}:title.adoc[{display_name}]\n"
    for entry in nav_entries[1:]:  # skip title.adoc itself, already the header
        nav_content += entry + "\n"
    
    nav_path = module_dir / "nav.adoc"
    nav_path.write_text(nav_content, encoding="utf-8")

    print(f"  OK  {guide_name}: {len([f for f in ordered if f not in SKIP_FILES and (src_dir/f).exists()])} pages")
    return module_name


def main():
    # Clean output
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True)

    # Create antora.yml
    antora_yml = """name: glassfish
title: Eclipse GlassFish Documentation
version: '8.0-SNAPSHOT'
asciidoc:
  attributes:
    productName: Eclipse GlassFish
    product-majorVersion: '8'
    jakartaee: '10'
    status: SNAPSHOT
nav:
"""

    modules = []
    for guide_name, display_name in GUIDES:
        print(f"Processing {guide_name}...")
        module_name = setup_guide_module(guide_name, display_name)
        if module_name:
            modules.append((module_name, display_name))

    # Add nav entries to antora.yml
    for module_name, _ in modules:
        antora_yml += f"  - modules/{module_name}/nav.adoc\n"

    (OUT_ROOT / "antora.yml").write_text(antora_yml, encoding="utf-8")

    # Create a ROOT module with the landing index page
    root_pages = OUT_ROOT / "modules" / "ROOT" / "pages"
    root_pages.mkdir(parents=True, exist_ok=True)
    
    index_content = """= Eclipse GlassFish Documentation
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
* xref:release-notes:title.adoc[Release Notes] — What's new and changed in this release.
"""
    (root_pages / "index.adoc").write_text(index_content, encoding="utf-8")

    # ROOT nav
    root_nav = OUT_ROOT / "modules" / "ROOT" / "nav.adoc"
    root_nav.write_text("* xref:ROOT:index.adoc[Home]\n", encoding="utf-8")

    # Prepend ROOT nav to antora.yml nav list
    antora_yml_final = antora_yml.replace(
        "nav:\n",
        "nav:\n  - modules/ROOT/nav.adoc\n"
    )
    (OUT_ROOT / "antora.yml").write_text(antora_yml_final, encoding="utf-8")

    print(f"\nDone. Content written to {OUT_ROOT}")
    print(f"Modules: {[m for m, _ in modules]}")


if __name__ == "__main__":
    main()
