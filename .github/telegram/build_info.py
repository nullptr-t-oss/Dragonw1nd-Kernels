"""Shared data-gathering helpers for build notifications.

Both telegram.py (Telegram Rich Message) and release_readme.py (GitHub
Release body) import this module so that hashing, feature lookup, and file
sizing are implemented exactly once and formatted differently per target.
Nothing in here should format markdown of any dialect — that stays in the
two calling scripts.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Stream-hashes a file so multi-GB artifacts don't need to fit in RAM."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(path: str) -> str:
    if not os.path.isfile(path):
        return "N/A"
    size = float(os.path.getsize(path))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"  # unreachable, satisfies linters expecting a return


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m else f"{s}s"


@dataclass
class Feature:
    id: str
    name: str
    description: str


def load_features(feat_ids: list[str], features_json_path: str) -> dict[str, list[Feature]]:
    """Returns {category: [Feature, ...]} for only the requested ids,
    preserving the category order from the JSON file. Unknown ids, and a
    missing/malformed features.json itself, are warned about on stderr and
    skipped rather than raised — a typo'd --feat flag or a moved/deleted
    catalog file shouldn't fail the whole build notification."""
    if not feat_ids:
        return {}

    try:
        with open(features_json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)["categories"]
    except FileNotFoundError:
        print(f"::warning::[build_info] features.json not found at {features_json_path} — sending without a feature list.", file=sys.stderr)
        return {}
    except (json.JSONDecodeError, KeyError) as e:
        print(f"::warning::[build_info] features.json is malformed ({e}) — sending without a feature list.", file=sys.stderr)
        return {}

    # Build a flat id -> (category, name, description) index once.
    index: dict[str, tuple[str, str, str]] = {}
    for category, feats in catalog.items():
        for fid, meta in feats.items():
            index[fid] = (category, meta["name"], meta["description"])

    grouped: dict[str, list[Feature]] = {}
    for fid in feat_ids:
        if fid not in index:
            print(f"::warning::[build_info] Unknown feature id, skipping: {fid}", file=sys.stderr)
            continue
        category, name, desc = index[fid]
        grouped.setdefault(category, []).append(Feature(fid, name, desc))

    # Preserve catalog category order, not the order --feat flags were given.
    ordered = {cat: grouped[cat] for cat in catalog if cat in grouped}
    return ordered


@dataclass
class FileEntry:
    path: str
    attach_id: str
    size: str
    sha256: str


def collect_files(paths: list[str]) -> list[FileEntry]:
    entries = []
    for path in paths:
        if not os.path.isfile(path):
            print(f"::warning::[build_info] File not found, skipping: {path}", file=sys.stderr)
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        attach_id = "".join(c if c.isalnum() else "_" for c in stem)
        entries.append(FileEntry(
            path=path,
            attach_id=attach_id,
            size=human_size(path),
            sha256=sha256_file(path),
        ))
    return entries


@dataclass
class GitHubContext:
    repository: str
    sha: str
    short_sha: str
    run_id: str
    run_number: str
    actor: str
    ref_name: str

    @property
    def commit_url(self) -> str:
        return f"https://github.com/{self.repository}/commit/{self.sha}"

    @property
    def run_url(self) -> str:
        return f"https://github.com/{self.repository}/actions/runs/{self.run_id}"


def github_context() -> GitHubContext:
    sha = os.environ.get("GITHUB_SHA", "")
    return GitHubContext(
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        sha=sha,
        short_sha=sha[:7],
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        run_number=os.environ.get("GITHUB_RUN_NUMBER", ""),
        actor=os.environ.get("GITHUB_ACTOR", ""),
        ref_name=os.environ.get("GITHUB_REF_NAME", ""),
    )
