"""Render the summary CSVs into a single self-contained ``index.html``.

The output embeds the Plotly.js library, CSS, JS, and the aggregated data inline
so it can be hosted on GitHub Pages (or opened from disk) with zero backend and
zero external network requests. Both reports (Building Yields and Religion Yields)
are bundled into the one file; a Report Type dropdown switches between them in-page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.offline as po

from .config import Config
from .metadata import BUILDING_FILTER_ERAS, ERA_LUT, Metadata, load_metadata

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Yield ordering for the selector (preferred order first, rest appended A-Z).
PREFERRED_YIELD_ORDER = [
    "Production",
    "Gold",
    "Science",
    "Culture",
    "Faith",
    "Food",
    "Border Growth Points",
    "Tourism",
]

# Religion report yield preference (Faith leads since it's the religion currency).
RELIGION_PREFERRED_YIELD_ORDER = [
    "Faith",
    "Production",
    "Gold",
    "Science",
    "Food",
    "Culture",
    "Tourism",
]

# Belief sections, in the fixed display order used by the right sidebar.
RELIGION_BELIEF_TYPE_ORDER = ["Pantheon", "Founder", "Follower", "Enhancer", "Reformation"]
# Belief types active (and thus shown) by default — matches the wireframe.
RELIGION_DEFAULT_BELIEF_TYPES = ["Pantheon", "Founder", "Follower"]

# Display eras shown by default (matches the wireframe).
DEFAULT_DISPLAY_ERAS = ["Ancient", "Classical", "Medieval", "Renaissance"]

_VALUE_COLS = ["BaseYields", "BonusYields", "InstantYields"]


def _order_yields(present: set[str], preferred: list[str] = PREFERRED_YIELD_ORDER) -> list[str]:
    ordered = [y for y in preferred if y in present]
    ordered += sorted(present - set(ordered))
    return ordered


def _nested_data(df: pd.DataFrame) -> dict:
    """yield -> era -> building -> {base, bonus, instant} (rounded)."""
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for row in df.itertuples(index=False):
        out.setdefault(row.Yield, {}).setdefault(row.Era, {})[row.Building] = {
            "base": round(float(row.BaseYields), 4),
            "bonus": round(float(row.BonusYields), 4),
            "instant": round(float(row.InstantYields), 4),
        }
    return out


def _buildings_by_yield(df: pd.DataFrame) -> dict[str, list[str]]:
    """yield -> sorted buildings that have any nonzero yield in that category."""
    has_value = df[_VALUE_COLS].abs().sum(axis=1) > 0
    sub = df[has_value]
    out: dict[str, list[str]] = {}
    for yld, group in sub.groupby("Yield"):
        out[yld] = sorted(group["Building"].unique())
    return out


def _build_tree(meta: Metadata, buildings_with_data: set[str]) -> list[dict]:
    """Ordered display tree: non-unique buildings A-Z, uniques indented under base.

    Only includes buildings that (or whose group children) appear in the data.
    """
    tree: list[dict] = []
    non_unique = sorted(
        b for b in buildings_with_data if b not in meta.unique_to_base
    )
    # Bases that have unique children but themselves lack data still head a group.
    base_candidates = set(non_unique)
    for base in meta.unique_groups:
        if any(u in buildings_with_data for u in meta.unique_groups[base]):
            base_candidates.add(base)

    for base in sorted(base_candidates):
        children = sorted(
            u for u in meta.unique_groups.get(base, []) if u in buildings_with_data
        )
        if base not in buildings_with_data and not children:
            continue
        tree.append({"name": base, "children": children})
    return tree


def _building_info_payload(meta: Metadata, buildings: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in buildings:
        info = meta.buildings.get(name)
        if info is None:
            out[name] = {"era": None, "ww": False, "nw": False, "rel": False}
        else:
            out[name] = {
                "era": info.era,
                "ww": info.is_world_wonder,
                "nw": info.is_national_wonder,
                "rel": info.is_religious,
            }
    return out


def build_building_payload(cfg: Config) -> dict:
    meta = load_metadata()
    turn_df = pd.read_csv(cfg.turn_average_path)
    total_df = pd.read_csv(cfg.era_totals_path)

    present_yields = set(turn_df["Yield"]) | set(total_df["Yield"])
    buildings_with_data = set(turn_df["Building"]) | set(total_df["Building"])

    return {
        "yields": _order_yields(present_yields),
        "eraOrder": list(ERA_LUT.values()),
        "defaultDisplayEras": DEFAULT_DISPLAY_ERAS,
        "buildingFilterEras": BUILDING_FILTER_ERAS,
        "buildingInfo": _building_info_payload(meta, buildings_with_data),
        "uniqueBases": sorted(
            b for b in meta.unique_groups if b in buildings_with_data
            or any(u in buildings_with_data for u in meta.unique_groups[b])
        ),
        "uniqueToBase": {
            u: b for u, b in meta.unique_to_base.items() if u in buildings_with_data
        },
        "tree": _build_tree(meta, buildings_with_data),
        "buildingsByYield": _buildings_by_yield(
            pd.concat([turn_df, total_df], ignore_index=True)
        ),
        "data": {
            "turn": _nested_data(turn_df),
            "total": _nested_data(total_df),
        },
    }


# ---------------------------------------------------------------------------
# Religion report payload
# ---------------------------------------------------------------------------

def _religion_nested_data(df: pd.DataFrame) -> dict:
    """yield -> era -> belief -> {owner, follower} (rounded)."""
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for row in df.itertuples(index=False):
        out.setdefault(row.Yield, {}).setdefault(row.Era, {})[row.Belief] = {
            "owner": round(float(row.YieldTotalForOwner), 4),
            "follower": round(float(row.YieldTotalForFollower), 4),
        }
    return out


def _beliefs_by_type(df: pd.DataFrame) -> dict[str, list[str]]:
    """BeliefType -> sorted list of beliefs of that type."""
    out: dict[str, list[str]] = {}
    for bt, group in df.groupby("BeliefType"):
        out[bt] = sorted(group["Belief"].unique())
    return out


def _belief_yields(df: pd.DataFrame) -> dict[str, list[str]]:
    """belief -> sorted yields it has any nonzero (owner or follower) value for."""
    has_value = (df["YieldTotalForOwner"].abs() + df["YieldTotalForFollower"].abs()) > 0
    sub = df[has_value]
    out: dict[str, list[str]] = {}
    for belief, group in sub.groupby("Belief"):
        out[belief] = sorted(group["Yield"].unique())
    return out


def build_religion_payload(cfg: Config) -> dict:
    turn_df = pd.read_csv(cfg.religion_turn_average_path)
    total_df = pd.read_csv(cfg.religion_era_totals_path)
    combined = pd.concat([turn_df, total_df], ignore_index=True)

    present_yields = set(turn_df["Yield"]) | set(total_df["Yield"])

    return {
        "yields": _order_yields(present_yields, RELIGION_PREFERRED_YIELD_ORDER),
        "beliefTypes": RELIGION_BELIEF_TYPE_ORDER,
        "defaultBeliefTypes": RELIGION_DEFAULT_BELIEF_TYPES,
        "eraOrder": list(ERA_LUT.values()),
        "defaultDisplayEras": DEFAULT_DISPLAY_ERAS,
        "beliefsByType": _beliefs_by_type(combined),
        "beliefYields": _belief_yields(combined),
        "data": {
            "turn": _religion_nested_data(turn_df),
            "total": _religion_nested_data(total_df),
        },
    }


def render(cfg: Config) -> Path:
    payload = {
        "defaultReport": "building",
        "building": build_building_payload(cfg),
        "religion": build_religion_payload(cfg),
    }
    template = (ASSETS_DIR / "template.html").read_text(encoding="utf-8")
    styles = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (ASSETS_DIR / "app.js").read_text(encoding="utf-8")
    religion_js = (ASSETS_DIR / "religion.js").read_text(encoding="utf-8")
    app_js = app_js + "\n" + religion_js
    plotly_js = po.get_plotlyjs()

    html = (
        template.replace("/*__STYLES__*/", styles)
        .replace("/*__PLOTLYJS__*/", plotly_js)
        .replace(
            "/*__DATA__*/",
            "window.PAYLOAD = " + json.dumps(payload, ensure_ascii=False) + ";",
        )
        .replace("/*__APPJS__*/", app_js)
    )

    cfg.publish_dir.mkdir(parents=True, exist_ok=True)
    cfg.index_html_path.write_text(html, encoding="utf-8")
    size_mb = cfg.index_html_path.stat().st_size / 1_048_576
    print(f"[render] wrote {cfg.index_html_path} ({size_mb:.1f} MB)")
    return cfg.index_html_path
