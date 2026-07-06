"""Build the Plotly Explorer dashboard (Building + Religion + Unit reports).

Pipeline: load config -> ensure intermediate summaries (regenerated only when the
source DB changes) -> render a single self-contained ``index.html`` into
``PUBLISH_DIR``.
"""

from __future__ import annotations

import argparse

from .aggregate import (
    ensure_game_summaries,
    ensure_policies_performance_summaries,
    ensure_religion_performance_summaries,
    ensure_religion_summaries,
    ensure_summaries,
    ensure_unit_summaries,
)
from .config import load_config
from .render import render


def main() -> None:
    parser = argparse.ArgumentParser(prog="plotly-explorer")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the intermediate summaries even if the cache looks fresh.",
    )
    # Dataset descriptors surfaced on the Civs Overview KPI cards. Supplied by
    # the launcher .bat files; defaults keep a bare `python -m plotly_explorer`
    # working.
    parser.add_argument("--patch", default="5.3.3", help="VP patch version.")
    parser.add_argument("--difficulty", default="Emperor", help="Game difficulty.")
    parser.add_argument("--mapscript", default="Communitu 3.2.0", help="Map script.")
    parser.add_argument("--size", default="Standard", help="Map size.")
    args = parser.parse_args()

    cfg = load_config()
    print(f"[config] db_type={cfg.db_type} db={cfg.db_path}")
    ensure_summaries(cfg, force=args.force)
    ensure_religion_summaries(cfg, force=args.force)
    ensure_unit_summaries(cfg, force=args.force)
    ensure_game_summaries(cfg, force=args.force)
    ensure_religion_performance_summaries(cfg, force=args.force)
    ensure_policies_performance_summaries(cfg, force=args.force)
    out = render(
        cfg,
        patch=args.patch,
        difficulty=args.difficulty,
        mapscript=args.mapscript,
        size=args.size,
    )
    print(f"[done] open {out}")


if __name__ == "__main__":
    main()
