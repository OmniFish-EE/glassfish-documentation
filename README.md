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
- Every 5 minutes, only when a new upstream commit touches `docs/` in `eclipse-ee4j/glassfish`
- Every day at 03:00 UTC (full rebuild)
- On demand via the **Actions** tab → **Build and Deploy Documentation** → **Run workflow**

## Repository structure

```
.
├── antora-playbook.yml          # Antora build configuration
├── antora-ui-default.zip        # Antora default UI bundle (base theme)
├── build_antora_content.py      # Transforms JBake adoc sources and fixes xrefs
├── local-build/
│   ├── build-site.sh            # Builds the site locally (steps 1–5)
│   └── serve-site.sh            # Serves the site; supports --watch for auto-rebuild
├── supplemental-ui/             # Custom GlassFish theme (CSS, header, footer)
│   ├── css/glassfish.css
│   ├── partials/header-content.hbs
│   ├── partials/footer-content.hbs
│   ├── partials/head-styles.hbs
│   └── img/glassfish-logo.png
└── .github/workflows/
    ├── build-and-deploy.yml     # GitHub Pages build + deploy workflow
    └── upstream-docs-listener.yml # Polls upstream docs changes and triggers deploy
```

The following directories are generated at build time and are not committed:

- `glassfish-repo/` — shallow clone of the upstream GlassFish repository
- `antora-content/` — processed Antora content source
- `build/` — generated static site

## Building locally

Two convenience scripts in `local-build/` cover the most common workflows.

### Prerequisites

- Node.js (for Antora — installed automatically if missing)
- Python 3
- Git
- `inotify-tools` (Linux only, required for `--watch` mode): `sudo apt-get install inotify-tools`

### Build the site

```bash
bash local-build/build-site.sh
```

This script:
1. Installs Antora tooling via npm (skipped if already installed)
2. Clones or updates the upstream GlassFish docs (sparse checkout of `docs/`)
3. Transforms the sources into Antora layout (includes xref fixes)
4. Initialises the Antora content git repo
5. Builds the static site into `build/site/`

### Serve the site

```bash
bash local-build/serve-site.sh
```

Serves the pre-built site at http://localhost:5000. Pass a port number to use a different port:

```bash
bash local-build/serve-site.sh 8080
```

### Serve with auto-rebuild on changes

```bash
bash local-build/serve-site.sh --watch
```

Runs a full build first, then watches for file changes and rebuilds automatically:

- Changes in `supplemental-ui/`, `antora-playbook.yml`, or `antora-content/` trigger a **fast rebuild** (Antora only).
- Changes in `glassfish-repo/docs/`, `build_antora_content.py`, or `docs-config.yml` trigger a **full rebuild** (transform + Antora).

Open http://localhost:5000/glassfish/8.0-SNAPSHOT/index.html to view the site.

### Manual steps (fallback)

If the scripts do not work, you can run each step manually:

```bash
# Install Antora
npm install -g @antora/cli@3.1 @antora/site-generator@3.1 @antora/lunr-extension

# Clone the GlassFish source docs
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/eclipse-ee4j/glassfish.git glassfish-repo
cd glassfish-repo && git sparse-checkout set docs && cd ..

# Transform sources (includes xref fixes)
python3 build_antora_content.py

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
