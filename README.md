# Eclipse GlassFish Documentation Site

This repository builds and hosts the [Eclipse GlassFish](https://glassfish.org) documentation as a static website using [Antora](https://antora.org), with full-text search powered by [Lunr](https://lunrjs.com).

The live site is published at: **https://omnifish-ee.github.io/glassfish-documentation**

## How it works

The AsciiDoc sources live in the upstream [eclipse-ee4j/glassfish](https://github.com/eclipse-ee4j/glassfish/tree/main/docs) repository. This repository contains:

- The build scripts that transform those sources into an Antora-compatible layout
- The Antora playbook (`antora-playbook.yml`) that drives the site generation
- A custom UI theme (`supplemental-ui/`) that matches the glassfish.org style
- A GitHub Actions workflow that rebuilds and redeploys the site automatically

## Automatic rebuilds

The site rebuilds automatically:

- On every push to `main` in this repository (e.g. theme or config changes)
- Every night at 03:00 UTC, picking up any new commits from the upstream GlassFish repo
- On demand via the **Actions** tab → **Build and Deploy Documentation** → **Run workflow**

## Repository structure

```
.
├── antora-playbook.yml          # Antora build configuration
├── antora-ui-default.zip        # Antora default UI bundle (base theme)
├── build_antora_content.py      # Transforms JBake adoc sources to Antora layout
├── fix_xrefs.py                 # Fixes cross-guide xref links for Antora
├── supplemental-ui/             # Custom GlassFish theme (CSS, header, footer)
│   ├── css/glassfish.css
│   ├── partials/header-content.hbs
│   ├── partials/footer-content.hbs
│   ├── partials/head-styles.hbs
│   └── img/glassfish-logo.png
└── .github/workflows/
    └── build-and-deploy.yml     # GitHub Actions workflow
```

The following directories are generated at build time and are not committed:

- `glassfish-repo/` — shallow clone of the upstream GlassFish repository
- `antora-content/` — processed Antora content source
- `build/` — generated static site

## Building locally

```bash
# Install Antora
npm install -g @antora/cli@3.1 @antora/site-generator@3.1 @antora/lunr-extension

# Clone the GlassFish source docs
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/eclipse-ee4j/glassfish.git glassfish-repo
cd glassfish-repo && git sparse-checkout set docs && cd ..

# Transform sources and fix xrefs
python3 build_antora_content.py
python3 fix_xrefs.py

# Initialise the content git repo (required by Antora)
cd antora-content
git init && git add -A && git commit -m "local build"
cd ..

# Build the site
antora antora-playbook.yml --to-dir build/site

# Serve locally
cd build/site && python3 -m http.server 5000
# Open http://localhost:5000/glassfish/8.0-SNAPSHOT/index.html
```

## Future improvements

- Landing page with guide cards grouped by audience (Developer / Admin / Architect)
- Jakarta EE / MicroProfile spec cross-reference links
- "What's new" page surfaced from release notes
- "View source on GitHub" link per page
- Support for older GlassFish versions (7.x)
