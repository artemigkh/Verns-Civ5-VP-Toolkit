"""Build the Plotly Explorer dashboard (Building + Religion yield reports).

Pipeline: load config -> ensure intermediate summaries (regenerated only when the
source DB changes) -> render a single self-contained ``index.html`` into
``PUBLISH_DIR``.
"""

from __future__ import annotations

import argparse

from .aggregate import ensure_religion_summaries, ensure_summaries
from .config import load_config
from .render import render


def main() -> None:
    parser = argparse.ArgumentParser(prog="plotly-explorer")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the intermediate summaries even if the cache looks fresh.",
    )
    args = parser.parse_args()

    cfg = load_config()
    print(f"[config] db_type={cfg.db_type} db={cfg.db_path}")
    ensure_summaries(cfg, force=args.force)
    ensure_religion_summaries(cfg, force=args.force)
    out = render(cfg)
    print(f"[done] open {out}")


if __name__ == "__main__":
    main()
