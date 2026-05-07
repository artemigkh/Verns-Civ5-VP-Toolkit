"""Deduplicate completed-game tar bundles by GameResult_Log.csv contents.

Each bundle is an uncompressed tar containing per-file gzip blobs. We extract
``GameResult_Log.csv.gz`` from every bundle, build a {csv-bytes -> [paths]}
table, and for each duplicate group keep only the oldest bundle (by mtime,
tie-broken by name) and delete the rest.

Usage:
    python -m autoplay.scripts.dedupe_complete_bundles <complete_dir> [--dry-run]
"""

from __future__ import annotations

import argparse
import gzip
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

GAME_RESULT_NAME = "GameResult_Log.csv.gz"


def extract_game_result(tar_path: Path) -> bytes | None:
    try:
        with tarfile.open(tar_path, mode="r") as tar:
            try:
                member = tar.getmember(GAME_RESULT_NAME)
            except KeyError:
                return None
            fh = tar.extractfile(member)
            if fh is None:
                return None
            return gzip.decompress(fh.read())
    except (tarfile.TarError, OSError, EOFError) as exc:
        print(f"  ! could not read {tar_path.name}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("complete_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    complete_dir: Path = args.complete_dir
    if not complete_dir.is_dir():
        print(f"not a directory: {complete_dir}", file=sys.stderr)
        return 2

    tars = sorted(complete_dir.glob("*.tar"))
    print(f"scanning {len(tars)} bundle(s) under {complete_dir}")

    groups: dict[bytes, list[Path]] = defaultdict(list)
    unreadable: list[Path] = []
    missing: list[Path] = []
    for i, p in enumerate(tars, start=1):
        if i % 25 == 0 or i == len(tars):
            print(f"  [{i}/{len(tars)}] scanned", flush=True)
        csv = extract_game_result(p)
        if csv is None:
            # Distinguish "no member" vs "tar broken" — we just skip both.
            unreadable.append(p)
            continue
        if not csv.strip():
            missing.append(p)
            continue
        groups[csv].append(p)

    dup_groups = [paths for paths in groups.values() if len(paths) > 1]
    total_dups = sum(len(g) - 1 for g in dup_groups)
    print(
        f"unique game results: {len(groups)}, "
        f"duplicate groups: {len(dup_groups)}, "
        f"redundant bundles to delete: {total_dups}, "
        f"unreadable/skipped: {len(unreadable)}, "
        f"empty-result: {len(missing)}"
    )

    deleted = 0
    for paths in dup_groups:
        # Oldest = smallest mtime; tie-break on name (ISO timestamp filenames
        # already sort chronologically).
        paths_sorted = sorted(paths, key=lambda p: (p.stat().st_mtime, p.name))
        keep = paths_sorted[0]
        for victim in paths_sorted[1:]:
            print(f"  delete {victim.name} (dup of {keep.name})")
            if not args.dry_run:
                try:
                    victim.unlink()
                    deleted += 1
                except OSError as exc:
                    print(f"    ! failed to delete: {exc}", file=sys.stderr)

    suffix = " (dry-run)" if args.dry_run else ""
    print(f"deleted {deleted} bundle(s){suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
