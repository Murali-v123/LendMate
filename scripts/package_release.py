#!/usr/bin/env python3
"""
LendMate Release Packaging Script.

Creates a clean, production-ready source archive (lendmate_release.zip)
strictly excluding development artifacts, secrets, and environment files:
  - .env, .env.*
  - venv/, .venv/
  - __pycache__/, *.pyc, *.pyo, *.pyd
  - staticfiles/ (collected assets; rebuilt during container build)
  - .git/, .github/
  - .idea/, .vscode/
  - *.log, logs/
  - temporary files (*.tmp, *~, *.swp)
  - database backups (*.sql)
  - existing ZIP archives (*.zip)

Ensures implementation_plan.md is included in the release root.
"""
import fnmatch
import os
import sys
import zipfile
from pathlib import Path

# Project root is the parent directory of scripts/
ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_ZIP = ROOT_DIR / "lendmate_release.zip"

# Exact directories to exclude entirely
EXCLUDE_DIRS = {
    "venv",
    ".venv",
    "__pycache__",
    "staticfiles",
    ".git",
    ".github",
    ".idea",
    ".vscode",
    "logs",
    "backups",
}

# Glob patterns to exclude
EXCLUDE_GLOBS = [
    ".env",
    ".env.*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.sql",
    "*.zip",
    "*.tmp",
    "*~",
    "*.swp",
]


def should_exclude(rel_path: Path) -> bool:
    """Check whether a path should be excluded from the release archive."""
    # Explicitly ensure .env.example is always included in the release
    if rel_path.name == ".env.example":
        return False

    parts = rel_path.parts

    # Exclude if any parent directory is in EXCLUDE_DIRS
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True

    # Exclude if filename matches any pattern
    name = rel_path.name
    for pattern in EXCLUDE_GLOBS:
        if fnmatch.fnmatch(name, pattern):
            return True

    return False


def create_release_zip(output_path: Path = OUTPUT_ZIP):
    """Package the project into a release zip file."""
    print(f"[INFO] Packaging LendMate release from: {ROOT_DIR}")
    print(f"[INFO] Target archive: {output_path}")

    # Remove existing output archive if present
    if output_path.exists():
        output_path.unlink()

    included_count = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT_DIR):
            # Prune excluded directories in-place to avoid descending into them
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in sorted(files):
                abs_file = Path(root) / file
                rel_file = abs_file.relative_to(ROOT_DIR)

                if should_exclude(rel_file):
                    continue

                zf.write(abs_file, arcname=str(rel_file).replace("\\", "/"))
                included_count += 1
                total_uncompressed_bytes += abs_file.stat().st_size

    archive_size = output_path.stat().st_size
    print(f"[SUCCESS] Packaged {included_count} files.")
    print(f"          Archive size : {archive_size:,} bytes ({archive_size / 1024 / 1024:.2f} MB)")
    print(f"          Uncompressed : {total_uncompressed_bytes:,} bytes ({total_uncompressed_bytes / 1024 / 1024:.2f} MB)")
    return output_path


if __name__ == "__main__":
    create_release_zip()
