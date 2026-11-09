---
name: gitea-packages
description: Use when locating or downloading generic Gitea packages, including test or build artifacts produced by CI pipelines.
---

# Gitea packages

Use `python scripts/gitea_packages.py` from the repository root.

```bash
python scripts/gitea_packages.py list --query NAME --page 1 --limit 50
python scripts/gitea_packages.py versions PACKAGE
python scripts/gitea_packages.py get PACKAGE VERSION
python scripts/gitea_packages.py files PACKAGE VERSION
python scripts/gitea_packages.py download PACKAGE VERSION FILENAME
```

The owner defaults to `freesearch`; use `--owner OWNER` before the subcommand to change it. Search filters package names, not file contents. Check subsequent pages when results fill a page. Downloads are streamed to the gitignored `.gitea-packages/` directory at the repository root, using the artifact filename. The script creates the directory when needed and does not overwrite existing files.