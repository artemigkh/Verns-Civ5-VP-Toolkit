"""Render the summary CSVs into a single self-contained ``index.html``.

The output embeds the Plotly.js library, CSS, JS, and the aggregated data inline
so it can be hosted on GitHub Pages (or opened from disk) with zero backend and
zero external network requests. Both reports (Building Yields and Religion Yields)
are bundled into the one file; a Report Type dropdown switches between them in-page.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import plotly.offline as po

from .aggregate.policies_performance import BRANCH_ORDER, SHOWN_VICTORY_TYPES
from .config import Config
from .metadata import (
    BUILDING_FILTER_ERAS,
    ERA_LUT,
    UNIT_CATEGORIES,
    UNIT_FILTER_ERAS,
    Metadata,
    load_civ_list,
    load_metadata,
    load_unit_metadata,
)

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
    """yield -> era -> building -> {base, bonus, instant, n} (rounded)."""
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for row in df.itertuples(index=False):
        out.setdefault(row.Yield, {}).setdefault(row.Era, {})[row.Building] = {
            "base": round(float(row.BaseYields), 4),
            "bonus": round(float(row.BonusYields), 4),
            "instant": round(float(row.InstantYields), 4),
            "n": int(row.N),  # sample size backing this block (tooltip "n=…")
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
            out[name] = {
                "era": None,
                "ww": False,
                "nw": False,
                "rel": False,
                "corp": False,
            }
        else:
            out[name] = {
                "era": info.era,
                "ww": info.is_world_wonder,
                "nw": info.is_national_wonder,
                "rel": info.is_religious,
                # Corp HQ and office share a single "Corporations" filter chip.
                "corp": info.is_corp_hq or info.is_corp_office,
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
    """yield -> era -> belief -> {owner, follower, nOwner, nFollower} (rounded)."""
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for row in df.itertuples(index=False):
        out.setdefault(row.Yield, {}).setdefault(row.Era, {})[row.Belief] = {
            "owner": round(float(row.YieldTotalForOwner), 4),
            "follower": round(float(row.YieldTotalForFollower), 4),
            # Per-benefactor sample sizes (tooltip "n=…").
            "nOwner": int(row.NOwner),
            "nFollower": int(row.NFollower),
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


# ---------------------------------------------------------------------------
# Unit-composition report payload
# ---------------------------------------------------------------------------

def _units_nested_data(df: pd.DataFrame) -> dict:
    """civ -> era -> unit -> {avg, n} (rounded avg + sample size)."""
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for row in df.itertuples(index=False):
        out.setdefault(row.Civ, {}).setdefault(row.Era, {})[row.Unit] = {
            "avg": round(float(row.AvgCount), 4),
            "n": int(row.N),  # sample size backing this bar (tooltip "n=…")
        }
    return out


def build_units_payload(cfg: Config) -> dict:
    unit_info = load_unit_metadata()
    df = pd.read_csv(cfg.unit_summary_path)

    # Combat classes offered as filter chips: genuine combat classes only
    # (civilian/support units are governed by the single "Non-Combat" chip).
    combat_classes = sorted(
        {
            info["combat_class"]
            for info in unit_info.values()
            if info["is_combat"] and info["combat_class"]
        }
    )
    domains = [d for d in ("Land", "Sea", "Air") if any(
        info["domain"] == d for info in unit_info.values()
    )]

    return {
        "civs": load_civ_list(),
        "eraOrder": list(ERA_LUT.values()),
        "defaultDisplayEras": DEFAULT_DISPLAY_ERAS,
        "unitFilterEras": UNIT_FILTER_ERAS,
        "combatClasses": combat_classes,
        "domains": domains,
        "legend": [
            {"key": key, "label": label, "color": color}
            for key, label, color in UNIT_CATEGORIES
        ],
        "unitInfo": unit_info,
        "data": _units_nested_data(df),
    }


# ---------------------------------------------------------------------------
# Civs Overview report payload
# ---------------------------------------------------------------------------

# Victory-type display order (matches the R reports' VICTORY_LEVELS).
VICTORY_ORDER = ["Cultural", "Science", "Domination", "Diplomatic", "Time"]


def _avg_winrate(gr: pd.DataFrame) -> float:
    """Average per-civ win rate across completed games.

    Total wins over total civ-participations, across COMPLETED games only (those
    with a recorded victory). One winner per game and N civs per game makes this
    1/N (e.g. 0.125 for 8-civ games); undecided games are excluded so incomplete
    runs can't drag the baseline below 1/N. Uses num_civs when present (added by
    the aggregator), else falls back to 0 (no baseline). Shared by the Overview
    win-rate chart and the Policies Performance win-rate chart's reference line.
    """
    vt = gr["victory_type"].fillna("").astype(str).str.strip()
    decided = gr[vt != ""]
    n_completed = int(len(decided))
    if "num_civs" in decided.columns:
        total_participations = int(decided["num_civs"].fillna(0).sum())
    else:
        total_participations = 0
    return (n_completed / total_participations) if total_participations else 0.0


def build_civs_payload(
    cfg: Config, patch: str, difficulty: str, mapscript: str, size: str
) -> dict:
    """KPI cards + victory-mix + per-civ win-rate data for the overview report.

    Victory share (donut) and turn distributions (violin/beeswarm) come from
    ``game_result.csv`` (one row per game); the win-rate stacked bars and the
    full stats table come from ``power_ranking.csv`` (one row per civ).
    """
    gr = pd.read_csv(cfg.game_result_path)
    pr = pd.read_csv(cfg.power_ranking_path)

    n_games = int(gr["game_id"].nunique())

    # Only decided games contribute to the victory mix (drop undecided rows
    # whose victory_type is blank/NaN).
    vt = gr["victory_type"].fillna("").astype(str).str.strip()
    decided = gr[vt != ""].copy()
    decided["victory_type"] = vt[vt != ""]

    present = [t for t in VICTORY_ORDER if (decided["victory_type"] == t).any()]
    counts = [int((decided["victory_type"] == t).sum()) for t in present]
    turns = {
        t: [int(x) for x in decided.loc[decided["victory_type"] == t, "turn"]]
        for t in present
    }
    # Victor civ per scatter point (aligned with ``turns``), for the tooltip.
    victors = {
        t: [
            str(c) if isinstance(c, str) else ""
            for c in decided.loc[decided["victory_type"] == t, "victory_civ"]
        ]
        for t in present
    }

    avg_winrate = _avg_winrate(gr)

    # Full per-civ table, sorted by win rate descending (JS formats to 2 dp).
    pr_sorted = pr.sort_values("winrate", ascending=False, kind="mergesort")
    rows = pr_sorted.to_dict("records")
    for row in rows:
        for key, value in row.items():
            if isinstance(value, float) and math.isnan(value):
                row[key] = None  # NaN pct cells (civs with no wins) -> null

    return {
        "kpis": {
            "patch": patch,
            "difficulty": difficulty,
            "mapscript": mapscript,
            "size": size,
            "games": n_games,
        },
        "victoryOrder": VICTORY_ORDER,
        "victory": {
            "present": present,
            "counts": counts,
            "turns": turns,
            "victors": victors,
        },
        "avgWinrate": avg_winrate,
        "table": {"columns": list(pr.columns), "rows": rows},
    }


# ---------------------------------------------------------------------------
# Religion Performance report payload
# ---------------------------------------------------------------------------

# Attainment-time milestone display order (matches the aggregator's labels).
ATTAINMENT_EVENT_ORDER = [
    "Pantheon Founded",
    "Religion Founded",
    "Religion Enhanced",
    "Religion Reformed",
]


def _kde_payload(kde_df: pd.DataFrame, moments_df: pd.DataFrame) -> dict:
    """event -> {x, density, mean, median, n}; only events with a fitted curve."""
    moments = {row.event_type: row for row in moments_df.itertuples(index=False)}
    out: dict[str, dict] = {}
    for event, group in kde_df.groupby("event_type"):
        m = moments.get(event)
        out[event] = {
            "x": [round(float(v), 4) for v in group["x"]],
            "density": [round(float(v), 8) for v in group["density"]],
            "mean": round(float(m.mean), 4) if m is not None else None,
            "median": round(float(m.median), 4) if m is not None else None,
            "n": int(m.n) if m is not None else 0,
        }
    return out


def _pick_perf_payload(df: pd.DataFrame) -> dict:
    """section -> [ {belief, chosen, wins, losses, winrate} ] (already sorted desc)."""
    out: dict[str, list[dict]] = {}
    for row in df.itertuples(index=False):
        chosen = int(row.chosen_count)
        wins = int(row.wins)
        out.setdefault(row.section, []).append(
            {
                "belief": row.belief,
                "chosen": chosen,
                "wins": wins,
                "losses": int(row.losses),
                # Win rate of the picking civ, as an integer percent (mockup labels).
                "winrate": round(100 * wins / chosen) if chosen else 0,
            }
        )
    return out


def build_religion_performance_payload(
    cfg: Config, patch: str, difficulty: str, mapscript: str, size: str
) -> dict:
    """Attainment-time KDE + belief pick/win-rate data for the performance report."""
    kde_df = pd.read_csv(cfg.religion_attainment_kde_path)
    moments_df = pd.read_csv(cfg.religion_attainment_moments_path)
    pick_df = pd.read_csv(cfg.religion_pick_performance_path)

    n_games = int(pd.read_csv(cfg.game_result_path)["game_id"].nunique())
    caption = (
        f"{n_games:,} Autoplay Games • VP {patch} • {mapscript} "
        f"• {size} Size • {difficulty} Difficulty"
    )

    present_events = set(kde_df["event_type"]) | set(moments_df["event_type"])
    return {
        "eventOrder": [e for e in ATTAINMENT_EVENT_ORDER if e in present_events],
        "kde": _kde_payload(kde_df, moments_df),
        "picks": _pick_perf_payload(pick_df),
        "caption": caption,
    }


# ---------------------------------------------------------------------------
# Policies Performance report payload
# ---------------------------------------------------------------------------

def build_policies_performance_payload(cfg: Config) -> dict:
    """Branch-open table/marginal + wins & win-rate by victory type per branch.

    ``policy_branch_opens.csv`` (per civ+branch) drives the shaded table and the
    marginal total-opens bar; ``policy_branch_wins.csv`` (per branch+victory type)
    drives the stacked wins bar. Win rate is derived here as wins over each
    branch's total opens, matching the mockup (e.g. Progress 269/1032 = 26%).
    """
    opens_df = pd.read_csv(cfg.policy_branch_opens_path)
    wins_df = pd.read_csv(cfg.policy_branch_wins_path)
    gr = pd.read_csv(cfg.game_result_path)

    present_branches = set(opens_df["branch"]) | set(wins_df["branch"])
    branches = [b for b in BRANCH_ORDER if b in present_branches]

    civs = sorted(opens_df["civ"].unique().tolist())

    opens: dict[str, dict[str, int]] = {}
    for row in opens_df.itertuples(index=False):
        opens.setdefault(row.civ, {})[row.branch] = int(row.opens)

    total_opens = {
        b: int(opens_df.loc[opens_df["branch"] == b, "opens"].sum()) for b in branches
    }

    wins: dict[str, dict[str, int]] = {}
    for row in wins_df.itertuples(index=False):
        wins.setdefault(row.branch, {})[row.victory_type] = int(row.wins)

    # Fixed 4-type order (legend always shows all four, as in the mockup).
    victory_order = list(SHOWN_VICTORY_TYPES)

    winrate: dict[str, dict[str, float]] = {}
    for b in branches:
        denom = total_opens.get(b, 0)
        branch_wins = wins.get(b, {})
        winrate[b] = {
            v: (branch_wins.get(v, 0) / denom if denom else 0.0) for v in victory_order
        }

    return {
        "branches": branches,
        "civs": civs,
        "opens": opens,
        "totalOpens": total_opens,
        "victoryOrder": victory_order,
        "wins": wins,
        "winrate": winrate,
        "avgWinrate": _avg_winrate(gr),
    }


def render(
    cfg: Config,
    *,
    patch: str = "5.3.3",
    difficulty: str = "Emperor",
    mapscript: str = "Communitu 3.2.0",
    size: str = "Standard",
) -> Path:
    payload = {
        "defaultReport": "civs",
        "civs": build_civs_payload(cfg, patch, difficulty, mapscript, size),
        "building": build_building_payload(cfg),
        "religion": build_religion_payload(cfg),
        "units": build_units_payload(cfg),
        "religion_performance": build_religion_performance_payload(
            cfg, patch, difficulty, mapscript, size
        ),
        "policies_performance": build_policies_performance_payload(cfg),
    }
    template = (ASSETS_DIR / "template.html").read_text(encoding="utf-8")
    styles = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (ASSETS_DIR / "app.js").read_text(encoding="utf-8")
    civs_js = (ASSETS_DIR / "civs.js").read_text(encoding="utf-8")
    religion_js = (ASSETS_DIR / "religion.js").read_text(encoding="utf-8")
    units_js = (ASSETS_DIR / "units.js").read_text(encoding="utf-8")
    religion_perf_js = (ASSETS_DIR / "religion_performance.js").read_text(encoding="utf-8")
    policies_perf_js = (ASSETS_DIR / "policies_performance.js").read_text(encoding="utf-8")
    # civs.js precedes religion.js because the report switcher (tail of
    # religion.js) runs at load and, since Civs Overview is the default report,
    # must find window.CivsReport already defined. religion_performance.js only
    # needs to have registered its module before the user switches to it, so it
    # can follow the switcher.
    app_js = (
        app_js
        + "\n" + civs_js
        + "\n" + religion_js
        + "\n" + units_js
        + "\n" + religion_perf_js
        + "\n" + policies_perf_js
    )
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
