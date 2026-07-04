#!/usr/bin/env python3
"""
Fix cross-guide xref references in the Antora content.

In Antora, cross-module xrefs must use the format:
  xref:module-name:page.adoc[text]

The original sources use:
  xref:guide-name.adoc[text]         -> cross-guide link to title page
  xref:page-within-guide.adoc[text]  -> same-module link (already correct)
  xref:../other-guide.adoc#anchor    -> relative cross-guide link

We detect cross-guide xrefs by checking if the filename stem matches a module name.
"""

import re
from pathlib import Path

CONTENT_ROOT = Path(__file__).parent / "antora-content" / "modules"

# All module names (guide names)
MODULE_NAMES = set(
    d.name for d in CONTENT_ROOT.iterdir()
    if d.is_dir() and d.name != "ROOT"
)

# All pages per module: module_name -> set of page filenames
MODULE_PAGES = {}
for module in MODULE_NAMES:
    pages_dir = CONTENT_ROOT / module / "pages"
    if pages_dir.exists():
        MODULE_PAGES[module] = {f.name for f in pages_dir.glob("*.adoc")}


def fix_xrefs_in_file(filepath: Path, current_module: str):
    """Fix xrefs in a single file."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    original = content

    def replace_xref(m):
        full_match = m.group(0)
        target = m.group(1)  # e.g. "reference-manual.adoc" or "../other.adoc"
        rest = m.group(2)    # e.g. "[text]" or "#anchor[text]"

        # Already has module prefix (module:page format) - skip
        if ":" in target and not target.startswith(".."):
            return full_match

        # Handle relative paths like ../other-guide.adoc
        if target.startswith("../"):
            target = target[3:]

        # Split anchor from filename
        if "#" in target:
            filename, anchor = target.split("#", 1)
            anchor = "#" + anchor
        else:
            filename = target
            anchor = ""

        # Normalize .html -> .adoc
        filename = re.sub(r"\.html$", ".adoc", filename)

        stem = filename.replace(".adoc", "")

        # Is this a cross-guide link to a guide's title page?
        if stem in MODULE_NAMES:
            if stem == current_module:
                # Self-referential: link to own title page
                return f"xref:title.adoc{anchor}{rest}"
            else:
                return f"xref:{stem}:title.adoc{anchor}{rest}"

        # Is this a page in a different module?
        for mod_name, pages in MODULE_PAGES.items():
            if mod_name != current_module and filename in pages:
                return f"xref:{mod_name}:{filename}{anchor}{rest}"

        # Same-module link, leave as-is (but fix .html extension)
        if filename != target.split("#")[0]:
            return f"xref:{filename}{anchor}{rest}"

        return full_match

    # Match xref:target[text] or xref:target#anchor[text]
    # The target can contain ../ for relative paths
    pattern = re.compile(r"xref:((?:\.\.\/)?[^[#:\s]+?)((?:#[^[\s]*)?(?:\[[^\]]*\])+)")
    content = pattern.sub(replace_xref, content)

    if content != original:
        filepath.write_text(content, encoding="utf-8")
        return True
    return False


def main():
    total_fixed = 0
    for module_name in sorted(MODULE_NAMES):
        pages_dir = CONTENT_ROOT / module_name / "pages"
        if not pages_dir.exists():
            continue
        module_fixed = 0
        for adoc_file in pages_dir.glob("*.adoc"):
            if fix_xrefs_in_file(adoc_file, module_name):
                module_fixed += 1
        if module_fixed:
            print(f"  {module_name}: fixed xrefs in {module_fixed} files")
        total_fixed += module_fixed
    print(f"\nTotal files with fixed xrefs: {total_fixed}")


if __name__ == "__main__":
    main()
