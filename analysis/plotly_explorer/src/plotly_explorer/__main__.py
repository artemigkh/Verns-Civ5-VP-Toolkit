"""Build the Plotly Explorer dashboard (Building + Religion + Unit reports).

Pipeline: load config -> for every dataset, ensure intermediate summaries
(regenerated only when the source DB changes) -> render the default dataset into
a self-contained ``index.html`` in ``PUBLISH_DIR`` and every other dataset into
a ``datasets/<id>.js`` beside it.
"""

from __future__ import annotations

import argparse

from .config import load_config
from .datasets import load_datasets
from .render import render


def main() -> None:
    parser = argparse.ArgumentParser(prog="plotly-explorer")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rebuild the default dataset's intermediate summaries even if the cache "
            "looks fresh. Other datasets still rebuild only when their DB changes."
        ),
    )
    # Default-dataset descriptors surfaced on the Civs Overview KPI cards.
    # Supplied by the launcher .bat files; defaults keep a bare
    # `python -m plotly_explorer` working. Other datasets take theirs from
    # datasets.toml.
    parser.add_argument("--patch", default="5.3.3", help="VP patch version.")
    parser.add_argument("--difficulty", default="Emperor", help="Game difficulty.")
    parser.add_argument("--mapscript", default="Communitu 3.2.0", help="Map script.")
    parser.add_argument("--size", default="Standard", help="Map size.")
    args = parser.parse_args()

    cfg = load_config()
    datasets = load_datasets(
        cfg,
        patch=args.patch,
        difficulty=args.difficulty,
        mapscript=args.mapscript,
        size=args.size,
    )
    for ds in datasets:
        tag = " (default)" if ds.is_default else ""
        print(f"[config] dataset {ds.id}{tag}: db_type={ds.cfg.db_type} db={ds.cfg.db_path}")
        ds.ensure_summaries(force=args.force and ds.is_default)
    out = render(cfg, datasets)
    print(f"[done] open {out}")


if __name__ == "__main__":
    main()
