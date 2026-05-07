"""Build a self-contained Plotly HTML dashboard combining 01c (donut + violin)
and 02 (per-civ stacked bars), with right-side color pickers that recolor the
charts live.

Output: ``analysis/output/interactive_dashboard.html``.

Defaults mirror the Python ``Report.ipynb`` ``vtc_lut`` palette:

    Cultural   #ff40ff
    Diplomatic #6600cc
    Science    #86f9fe
    Domination red
    Time       black

Background defaults to seaborn-v0_8's panel grey ``#eaeaf2``.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import plotly.offline as po
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

ANALYSIS_DIR = Path(__file__).resolve().parent
REPO_ROOT    = ANALYSIS_DIR.parent
DATA_DIR     = REPO_ROOT / "data" / "MP_AUTOPLAY_VP_5_2_3" / "intermediate_csvs"
OUTPUT_PATH  = ANALYSIS_DIR / "output" / "interactive_dashboard.html"

VICTORY_LEVELS = ["Cultural", "Science", "Domination", "Diplomatic", "Time"]

# Defaults from the Python Report.ipynb vtc_lut.
DEFAULTS: dict[str, str] = {
    "background": "#ffffff",   # white
    "Cultural":   "#ff40ff",
    "Science":    "#86f9fe",
    "Domination": "#ff0000",   # 'red'
    "Diplomatic": "#6600cc",
    "Time":       "#000000",   # 'black' (not user-controllable)
}

# Subset that gets a color picker on the page.
USER_COLOR_KEYS = ["background", "Cultural", "Science", "Domination", "Diplomatic"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_csv(name: str) -> pd.DataFrame:
    files = sorted(glob.glob(str(DATA_DIR / name / "part-*.csv")))
    if not files:
        raise FileNotFoundError(f"No CSV parts under {DATA_DIR / name}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def _build_data() -> dict[str, object]:
    game = _load_csv("game_result")
    pr   = _load_csv("power_ranking")

    # 01c: counts per victory type and per-type turn distributions.
    counts = (
        game["victory_type"]
        .value_counts()
        .reindex(VICTORY_LEVELS, fill_value=0)
        .astype(int)
        .tolist()
    )
    violin = {v: game.loc[game["victory_type"] == v, "turn"].astype(int).tolist()
              for v in VICTORY_LEVELS}
    n_games = int(len(game))

    # 02: per-civ, per-victory winrate shares stacked.
    vtype_cols = {
        "Cultural":   "culture_victories",
        "Science":    "science_victories",
        "Domination": "domination_victories",
        "Diplomatic": "diplomatic_victories",
        "Time":       "time_victories",
    }
    pr2 = pr.copy()
    for col in vtype_cols.values():
        pr2[col] = pd.to_numeric(pr2[col], errors="coerce").fillna(0)
    pr2["count_games"] = pd.to_numeric(pr2["count_games"], errors="coerce").fillna(0)
    safe_n = pr2["count_games"].where(pr2["count_games"] > 0, 1)
    for label, col in vtype_cols.items():
        pr2[f"share_{label}"] = pr2[col] / safe_n
    pr2["total_winrate"] = sum(pr2[f"share_{v}"] for v in VICTORY_LEVELS)
    pr2 = pr2.sort_values("total_winrate", ascending=False).reset_index(drop=True)

    return {
        "counts":  counts,
        "violin":  violin,
        "n_games": n_games,
        "civs":    pr2["civ"].tolist(),
        "shares":  {v: pr2[f"share_{v}"].tolist() for v in VICTORY_LEVELS},
        "totals":  pr2["total_winrate"].tolist(),
    }


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def _build_top_figure(data: dict[str, object]) -> go.Figure:
    """Donut (left) + violin per victory type (right)."""
    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "domain"}, {"type": "xy"}]],
        column_widths=[0.42, 0.58],
        subplot_titles=("Victory Type Share", "Victory Time Spread"),
        horizontal_spacing=0.08,
    )

    # Pie / donut. Trace 0.
    donut_colors = [DEFAULTS[v] for v in VICTORY_LEVELS]
    fig.add_trace(
        go.Pie(
            labels=VICTORY_LEVELS,
            values=data["counts"],
            hole=0.55,
            sort=False,
            direction="clockwise",
            marker=dict(
                colors=donut_colors,
                line=dict(color=DEFAULTS["background"], width=2),
            ),
            textinfo="label+percent",
            hoverinfo="skip",
            name="donut",
        ),
        row=1, col=1,
    )

    # Violin per victory type. Traces 1..5 (one per VICTORY_LEVELS entry).
    for v in VICTORY_LEVELS:
        ys = data["violin"][v]
        fig.add_trace(
            go.Violin(
                y=ys,
                x=[v] * len(ys),
                name=v,
                fillcolor=DEFAULTS[v],
                line_color=DEFAULTS[v],
                opacity=0.85,
                spanmode="hard",
                meanline_visible=True,
                points=False,
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1, col=2,
        )

    fig.update_layout(
        paper_bgcolor=DEFAULTS["background"],
        plot_bgcolor=DEFAULTS["background"],
        height=480,
        margin=dict(l=40, r=20, t=40, b=50),
        font=dict(family="Arial, sans-serif", size=13),
        hovermode=False,
    )
    fig.update_xaxes(
        title_text="Victory type",
        categoryorder="array", categoryarray=VICTORY_LEVELS,
        row=1, col=2,
    )
    fig.update_yaxes(title_text="Game-ending turn", row=1, col=2)
    return fig


def _build_bottom_figure(data: dict[str, object]) -> go.Figure:
    """Per-civ stacked bar of winrate by victory type."""
    fig = go.Figure()
    civs   = data["civs"]
    shares = data["shares"]
    totals = data["totals"]

    # Traces 0..4 are the stacked victory-type bars in VICTORY_LEVELS order.
    for v in VICTORY_LEVELS:
        fig.add_trace(go.Bar(
            x=civs, y=shares[v],
            name=v,
            marker=dict(
                color=DEFAULTS[v],
                line=dict(color=DEFAULTS["background"], width=0.5),
            ),
            hoverinfo="skip",
        ))

    # Trace 5: total-winrate text labels above each bar.
    fig.add_trace(go.Scatter(
        x=civs, y=totals,
        mode="text",
        text=[f"{t * 100:.0f}%" for t in totals],
        textposition="top center",
        showlegend=False,
        cliponaxis=False,
        textfont=dict(color="#444", size=11),
        hoverinfo="skip",
        name="totals",
    ))

    fig.add_hline(
        y=0.125, line_dash="dash", line_color="#555", line_width=1,
        annotation_text="average win rate (12.5%)",
        annotation_position="top right",
        annotation_font=dict(size=11, color="#444"),
    )

    fig.update_layout(
        barmode="stack",
        paper_bgcolor=DEFAULTS["background"],
        plot_bgcolor=DEFAULTS["background"],
        height=540,
        margin=dict(l=70, r=30, t=70, b=140),
        font=dict(family="Arial, sans-serif", size=13),
        hovermode=False,
        title=dict(
            text="Win Rate By Civilization",
            x=0.02, xanchor="left",
            font=dict(size=18),
        ),
        yaxis=dict(
            title="Win rate",
            tickformat=".0%",
            gridcolor="rgba(0,0,0,0.08)",
            zerolinecolor="rgba(0,0,0,0.15)",
        ),
        xaxis=dict(
            title="Civilization",
            tickangle=45,
            gridcolor="rgba(0,0,0,0.05)",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1.0,
            title=dict(text="Victory type"),
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def _trace_color_map() -> dict[str, dict[str, list[int]]]:
    """Return ``{chart_id: {victory_type: [trace_indices]}}``.

    The JS uses this to know which traces to recolor when a given color
    picker changes. Indices are stable because both figures are built in a
    fixed trace order above.
    """
    # Top figure: trace 0 = donut (special-cased in JS), traces 1..5 = violins
    # in VICTORY_LEVELS order.
    top: dict[str, list[int]] = {v: [i + 1] for i, v in enumerate(VICTORY_LEVELS)}
    # Bottom figure: traces 0..4 = stacked bars in VICTORY_LEVELS order.
    bot: dict[str, list[int]] = {v: [i] for i, v in enumerate(VICTORY_LEVELS)}
    return {"top": top, "bottom": bot}


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Civ5 VP Autoplay &mdash; Victory Mix &amp; Per-Civ Winrate</title>
<style>
  :root {
    --bg: BACKGROUND_DEFAULT;
    --panel-bg: rgba(255, 255, 255, 0.65);
    --panel-border: rgba(0, 0, 0, 0.12);
    --text: #1f2937;
    --muted: #6b7280;
  }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    transition: background 0.15s linear;
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 260px;
    gap: 16px;
    padding: 16px;
    box-sizing: border-box;
    min-height: 100vh;
  }
  .charts { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .card {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }
  .sidebar {
    position: sticky;
    top: 16px;
    align-self: start;
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    height: fit-content;
  }
  .sidebar h2 {
    margin: 0 0 4px;
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text);
  }
  .sidebar p { margin: 0 0 14px; font-size: 12px; color: var(--muted); }
  .picker-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px dashed rgba(0, 0, 0, 0.08);
  }
  .picker-row:last-of-type { border-bottom: 0; }
  .picker-row label { font-size: 13px; font-weight: 500; }
  .picker-row .swatch-wrap { display: flex; align-items: center; gap: 8px; }
  .picker-row input[type="color"] {
    width: 36px; height: 28px;
    border: 1px solid var(--panel-border);
    border-radius: 6px; padding: 0; background: transparent;
    cursor: pointer;
  }
  .picker-row .hex {
    font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
    font-size: 11px; color: var(--muted); min-width: 64px; text-align: right;
  }
  .reset-btn {
    margin-top: 14px; width: 100%; padding: 8px 10px;
    border: 1px solid var(--panel-border);
    border-radius: 8px; background: white;
    cursor: pointer; font-size: 13px; font-weight: 500;
  }
  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; }
    .sidebar { position: static; }
  }
</style>
</head>
<body>
<div class="layout">
  <div class="charts">
    <div class="card"><div id="chart-top"></div></div>
    <div class="card"><div id="chart-bottom"></div></div>
  </div>
  <aside class="sidebar">
    <h2>Colors</h2>
    <p>Live recolor &mdash; defaults match the Python report's <code>vtc_lut</code>.</p>
    PICKER_ROWS_HTML
    <button class="reset-btn" id="reset-colors">Reset to defaults</button>
  </aside>
</div>

<script>PLOTLY_JS</script>
<script>
(function () {
  const TOP_ID    = "chart-top";
  const BOTTOM_ID = "chart-bottom";

  const TOP_FIG    = TOP_FIG_JSON;
  const BOTTOM_FIG = BOTTOM_FIG_JSON;
  const DEFAULTS   = DEFAULTS_JSON;
  const TRACE_MAP  = TRACE_MAP_JSON;
  const VICTORY_LEVELS = VICTORY_LEVELS_JSON;

  const cfg = { responsive: true, displaylogo: false };
  Plotly.newPlot(TOP_ID,    TOP_FIG.data,    TOP_FIG.layout,    cfg);
  Plotly.newPlot(BOTTOM_ID, BOTTOM_FIG.data, BOTTOM_FIG.layout, cfg);

  // Track current colors so a victory-color change can rebuild the donut's
  // full marker.colors array (Plotly.restyle for nested marker.colors needs
  // the full vector, not a single-element edit).
  const current = Object.assign({}, DEFAULTS);

  function applyBackground(color) {
    current.background = color;
    document.documentElement.style.setProperty("--bg", color);
    Plotly.relayout(TOP_ID,    { paper_bgcolor: color, plot_bgcolor: color });
    Plotly.relayout(BOTTOM_ID, { paper_bgcolor: color, plot_bgcolor: color });
    // Slice/bar borders are drawn in the background color; recolor them too.
    Plotly.restyle(TOP_ID,    { "marker.line.color": color }, [0]);
    const barIdx = VICTORY_LEVELS.map((_, i) => i);
    Plotly.restyle(BOTTOM_ID, { "marker.line.color": color }, barIdx);
  }

  function applyVictoryColor(victory, color) {
    current[victory] = color;

    // Top figure: rebuild full donut color list, then recolor the matching
    // violin trace.
    const donutColors = VICTORY_LEVELS.map(v => current[v]);
    Plotly.restyle(TOP_ID, { "marker.colors": [donutColors] }, [0]);

    const topTraces = TRACE_MAP.top[victory] || [];
    if (topTraces.length) {
      Plotly.restyle(TOP_ID,
        { fillcolor: color, "line.color": color, "marker.color": color },
        topTraces);
    }

    // Bottom figure: matching stacked-bar trace.
    const botTraces = TRACE_MAP.bottom[victory] || [];
    if (botTraces.length) {
      Plotly.restyle(BOTTOM_ID, { "marker.color": color }, botTraces);
    }
  }

  function wirePicker(key) {
    const input = document.getElementById("color-" + key);
    const hex   = document.getElementById("hex-"   + key);
    if (!input) return;
    input.value = DEFAULTS[key];
    if (hex) hex.textContent = DEFAULTS[key].toLowerCase();
    input.addEventListener("input", () => {
      const c = input.value;
      if (hex) hex.textContent = c.toLowerCase();
      if (key === "background") applyBackground(c);
      else                      applyVictoryColor(key, c);
    });
  }

  USER_COLOR_KEYS_JSON.forEach(wirePicker);

  document.getElementById("reset-colors").addEventListener("click", () => {
    USER_COLOR_KEYS_JSON.forEach(k => {
      const input = document.getElementById("color-" + k);
      const hex   = document.getElementById("hex-"   + k);
      if (!input) return;
      input.value = DEFAULTS[k];
      if (hex) hex.textContent = DEFAULTS[k].toLowerCase();
      if (k === "background") applyBackground(DEFAULTS[k]);
      else                    applyVictoryColor(k, DEFAULTS[k]);
    });
  });
})();
</script>
</body>
</html>
"""


def _build_picker_rows_html(keys: list[str]) -> str:
    rows: list[str] = []
    for k in keys:
        label = "Background" if k == "background" else k
        rows.append(
            f'    <div class="picker-row">\n'
            f'      <label for="color-{k}">{label}</label>\n'
            f'      <span class="swatch-wrap">\n'
            f'        <span class="hex" id="hex-{k}">{DEFAULTS[k].lower()}</span>\n'
            f'        <input type="color" id="color-{k}" value="{DEFAULTS[k]}">\n'
            f'      </span>\n'
            f'    </div>'
        )
    return "\n".join(rows)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = _build_data()
    fig_top = _build_top_figure(data)
    fig_bot = _build_bottom_figure(data)

    top_json = json.loads(pio.to_json(fig_top))
    bot_json = json.loads(pio.to_json(fig_bot))
    plotlyjs = po.get_plotlyjs()

    html = (
        _HTML_TEMPLATE
        .replace("BACKGROUND_DEFAULT",   DEFAULTS["background"])
        .replace("PICKER_ROWS_HTML",     _build_picker_rows_html(USER_COLOR_KEYS))
        .replace("PLOTLY_JS",            plotlyjs)
        .replace("TOP_FIG_JSON",         json.dumps(top_json))
        .replace("BOTTOM_FIG_JSON",      json.dumps(bot_json))
        .replace("DEFAULTS_JSON",        json.dumps(DEFAULTS))
        .replace("TRACE_MAP_JSON",       json.dumps(_trace_color_map()))
        .replace("VICTORY_LEVELS_JSON",  json.dumps(VICTORY_LEVELS))
        .replace("USER_COLOR_KEYS_JSON", json.dumps(USER_COLOR_KEYS))
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
