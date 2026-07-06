"""Per-CSV, mtime-based caching for the intermediate summary CSVs.

Every aggregation writes its result to a CSV under ``INTERMEDIATE_DATA_DIR``. A
CSV is considered *fresh* when it exists and is at least as new as the source
DB file; otherwise it is rebuilt. This is per-CSV: if the process dies partway
through a run, a rerun only regenerates the CSVs that never completed (or that
predate a newer DB), not every CSV.

``ensure_csv`` also returns the (freshly built or cached) DataFrame so that a
downstream aggregation can reuse a shared intermediate without recomputing it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from ..config import Config


def source_mtime(cfg: Config) -> float:
    """Modification time of the backing source database file."""
    return os.path.getmtime(cfg.db_path)


def is_fresh(path: Path, cfg: Config) -> bool:
    """A CSV is fresh iff it exists and is no older than the source DB."""
    return path.exists() and os.path.getmtime(path) >= source_mtime(cfg)


def ensure_csv(
    cfg: Config,
    path: Path,
    builder: Callable[[], pd.DataFrame],
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Return the CSV at ``path``, rebuilding it if stale (or ``force``).

    On a cache hit the CSV is read back from disk; on a miss ``builder`` is
    called, its result written to ``path`` and returned. Either way the caller
    gets a DataFrame it can pass on to a dependent aggregation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if not force and is_fresh(path, cfg):
        print(f"[aggregate] cache fresh, reusing {path.name}")
        return pd.read_csv(path)

    print(f"[aggregate] building {path.name} from {cfg.db_path} ({cfg.db_type})")
    df = builder()
    df.to_csv(path, index=False)
    print(f"[aggregate] wrote {len(df)} rows to {path.name}")
    return df


def ensure_group(
    cfg: Config,
    paths: Iterable[Path],
    builder: Callable[[], tuple[pd.DataFrame, ...]],
    *,
    force: bool = False,
) -> tuple[pd.DataFrame, ...]:
    """Ensure several CSVs produced by a single build pass.

    Freshness is still evaluated per file, but because ``builder`` computes the
    whole set at once, a single missing/stale CSV triggers a rebuild of all of
    them. ``paths`` and the tuple returned by ``builder`` must line up in order.
    """
    paths = list(paths)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)

    if not force and all(is_fresh(p, cfg) for p in paths):
        names = ", ".join(p.name for p in paths)
        print(f"[aggregate] cache fresh, reusing {names}")
        return tuple(pd.read_csv(p) for p in paths)

    print(f"[aggregate] building {', '.join(p.name for p in paths)} from {cfg.db_path} ({cfg.db_type})")
    frames = builder()
    for path, frame in zip(paths, frames):
        frame.to_csv(path, index=False)
        print(f"[aggregate] wrote {len(frame)} rows to {path.name}")
    return frames
