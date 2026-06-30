#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Restore docs/archive/*.json (and .html) from the currently-deployed
GitHub Pages site before a new run starts.

WHY THIS EXISTS:
Each GitHub Actions run starts from a fresh `git checkout` of the repo.
docs/archive/ files are generated and deployed to Pages, but are
deliberately NOT committed back to git (to avoid permission issues and
keep the repo clean). That means a fresh checkout has NO history at all —
day-over-day deltas, the date-filter dropdown, and the 增长信号 (growth
signals) module would all silently see zero history on every single run.

This script "self-bootstraps" history by fetching the previously deployed
manifest.json + dated archive files directly from the live Pages URL and
writing them into the local docs/archive/ folder before the main
generator script runs. No git commit is needed — Pages itself is used as
the persistence layer.

Safe by design: any individual fetch failure is skipped with a warning,
never aborts the run. On the very first-ever run there's nothing to
restore yet, which is expected and not an error.
"""
import os
import sys
import time
from pathlib import Path

import requests

ARCHIVE_DIR = Path("docs/archive")
REQUEST_TIMEOUT = 15


def get_pages_base_url():
    """Derive the live Pages URL from the GITHUB_REPOSITORY env var
    (format 'owner/repo', automatically provided by GitHub Actions).
    Handles both project pages (owner.github.io/repo/) and user/org
    root pages (owner.github.io/) where repo == 'owner.github.io'."""
    repo_full = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo_full or "/" not in repo_full:
        return None
    owner, name = repo_full.split("/", 1)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{name}/"
    return f"https://{owner}.github.io/{name}/"


def main():
    base = get_pages_base_url()
    if not base:
        print("GITHUB_REPOSITORY not set — cannot determine Pages URL, skipping restore.")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_url = base + "archive/manifest.json"

    try:
        r = requests.get(manifest_url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"No existing manifest at {manifest_url} (HTTP {r.status_code}) "
                  f"— likely the first-ever run, nothing to restore.")
            return
        manifest = r.json()
    except Exception as e:
        print(f"Could not fetch manifest ({e}) — skipping restore, this run will "
              f"proceed with no prior history (expected on first run).")
        return

    if not isinstance(manifest, list):
        print("Manifest format unexpected — skipping restore.")
        return

    restored, skipped, failed = 0, 0, 0
    for item in manifest:
        date = item.get("date") if isinstance(item, dict) else None
        if not date:
            continue
        local_json = ARCHIVE_DIR / f"{date}.json"
        if local_json.exists():
            skipped += 1
            continue
        ok_any = False
        for ext in ("json", "html"):
            url = f"{base}archive/{date}.{ext}"
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    (ARCHIVE_DIR / f"{date}.{ext}").write_bytes(resp.content)
                    ok_any = True
            except Exception as e:
                print(f"  Failed to restore {date}.{ext}: {e}")
        if ok_any:
            restored += 1
        else:
            failed += 1
        time.sleep(0.15)  # be polite to Pages CDN

    print(f"Archive restore complete: {restored} restored, {skipped} already present, "
          f"{failed} failed (out of {len(manifest)} dates in manifest).")


if __name__ == "__main__":
    main()
