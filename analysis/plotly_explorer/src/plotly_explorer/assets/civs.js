/* Civs Overview report — a self-contained BI-style dashboard (no controls).

   Rows, top to bottom:
     1. KPI cards (patch / difficulty / mapscript / # games)
     2. Victory Type Share donut + Victory Time Spread violin/beeswarm
     3. Win Rate By Civilization stacked bars (full width)
     4. Full per-civ stats table (full width), sorted by win rate desc.

   Mirrors analysis/r_scripts/01_victory_mix.R and 02_winrate_by_civ.R using the
   dark victory palette (vtc_lut_b). */
(function () {
  "use strict";

  var P = window.PAYLOAD.civs;

  // Dark victory palette (matches common.R's vtc_lut_b).
  var VICTORY_COLORS = {
    Cultural: "#E700E7",
    Science: "#86f9fe",
    Domination: "#B22222",
    Diplomatic: "#6600cc",
    Time: "#ffffff",
  };

  // Victory type -> its win-count column in power_ranking.
  var VICTORY_COL = {
    Cultural: "culture_victories",
    Science: "science_victories",
    Domination: "domination_victories",
    Diplomatic: "diplomatic_victories",
    Time: "time_victories",
  };

  var BG = "#0e1117";
  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";
  var GRID = "rgba(255,255,255,0.07)";

  function hexToRgba(hex, a) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return (
      "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")"
    );
  }

  var PLOT_CONFIG = { displayModeBar: false, responsive: true };

  // -------------------------------------------------------------------------
  // Row 1 — KPI cards
  // -------------------------------------------------------------------------
  function buildKpis() {
    var host = document.getElementById("civs-kpi-row");
    host.innerHTML = "";
    var k = P.kpis;
    [
      { value: k.patch, title: "Patch Version" },
      { value: k.difficulty, title: "Difficulty" },
      { value: k.mapscript, title: "Mapscript" },
      { value: k.size, title: "Map Size" },
      { value: (k.games || 0).toLocaleString(), title: "# Games" },
    ].forEach(function (c) {
      var card = document.createElement("div");
      card.className = "civs-kpi";
      var v = document.createElement("div");
      v.className = "kpi-value";
      v.textContent = c.value;
      var t = document.createElement("div");
      t.className = "kpi-title";
      t.textContent = c.title;
      card.appendChild(v);
      card.appendChild(t);
      host.appendChild(card);
    });
  }

  // -------------------------------------------------------------------------
  // Row 2a — Victory Type Share donut
  // -------------------------------------------------------------------------
  function renderDonut() {
    var present = P.victory.present;
    var trace = {
      type: "pie",
      hole: 0.6,
      labels: present,
      values: P.victory.counts,
      marker: {
        colors: present.map(function (t) {
          return VICTORY_COLORS[t] || "#888888";
        }),
        line: { color: BG, width: 2 },
      },
      sort: false,
      direction: "clockwise",
      rotation: 0,
      texttemplate: "<b>%{label}</b><br>%{value}  (%{percent})",
      textposition: "outside",
      outsidetextfont: { color: TEXT, size: 13 },
      hovertemplate: "%{label}: %{value} (%{percent})<extra></extra>",
    };
    var layout = {
      title: {
        text: "Victory Type Share",
        font: { color: TEXT, size: 17 },
        x: 0.5,
        xanchor: "center",
      },
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      // Fixed (not auto) margins: automargin on outside pie labels thrashes
      // ("too many auto-margin redraws") when the flex container is resized.
      margin: { l: 70, r: 70, t: 50, b: 30 },
      font: { color: TEXT },
    };
    Plotly.react(document.getElementById("civs-donut"), [trace], layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Row 2b — Victory Time Spread violin + beeswarm (points overlaid)
  // -------------------------------------------------------------------------
  function renderViolin() {
    var present = P.victory.present;
    var traces = present.map(function (t) {
      var color = VICTORY_COLORS[t] || "#888888";
      var turns = P.victory.turns[t] || [];
      var victors = (P.victory.victors && P.victory.victors[t]) || [];
      return {
        type: "violin",
        name: t,
        x: turns.map(function () {
          return t;
        }),
        y: turns,
        // Victor civ per point, aligned with y; surfaced in the point tooltip.
        customdata: victors,
        fillcolor: hexToRgba(color, 0.85),
        line: { color: BG, width: 1 },
        points: "all",
        pointpos: 0,
        jitter: 0.6,
        scalemode: "width",
        width: 0.9,
        spanmode: "soft",
        marker: {
          color: color,
          size: 5,
          opacity: 0.9,
          line: { color: "#000000", width: 0.8 },
        },
        meanline: { visible: false },
        box: { visible: false },
        hoveron: "points",
        hovertemplate: "%{customdata}<br>" + t + " victory<br>Turn %{y}<extra></extra>",
        showlegend: false,
      };
    });
    var layout = {
      title: {
        text: "Victory Time Spread",
        font: { color: TEXT, size: 17 },
        x: 0.5,
        xanchor: "center",
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 60, r: 20, t: 50, b: 40 },
      font: { color: TEXT_DIM, size: 12 },
      violinmode: "overlay",
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: present,
        tickfont: { color: TEXT, size: 13 },
        gridcolor: "rgba(255,255,255,0.04)",
      },
      yaxis: {
        title: { text: "Game-ending turn", font: { color: TEXT_DIM, size: 12 } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
      },
      showlegend: false,
    };
    Plotly.react(document.getElementById("civs-violin"), traces, layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Row 3 — Win Rate By Civilization, stacked by victory type
  // -------------------------------------------------------------------------
  function winrateData() {
    var rows = P.table.rows;
    var order = P.victoryOrder;

    // Victory types with at least one win somewhere, in canonical order.
    var present = order.filter(function (t) {
      var col = VICTORY_COL[t];
      return rows.some(function (r) {
        return (r[col] || 0) > 0;
      });
    });

    // Per-civ share by victory type; total winrate = sum of shares.
    var civRows = rows.map(function (r) {
      var g = r.count_games || 0;
      var total = 0;
      present.forEach(function (t) {
        total += g ? (r[VICTORY_COL[t]] || 0) / g : 0;
      });
      return { civ: r.civ, row: r, total: total };
    });
    civRows.sort(function (a, b) {
      return b.total - a.total;
    });

    // Average win-rate baseline comes from the payload: wins / participations
    // across completed games only (1/N for N-civ games), computed by the
    // aggregator so unfinished/test games can't skew it.
    var avg = typeof P.avgWinrate === "number" ? P.avgWinrate : 0;

    return { present: present, civRows: civRows, avg: avg };
  }

  function renderWinrate() {
    var d = winrateData();
    var civs = d.civRows.map(function (c) {
      return c.civ;
    });

    var traces = d.present.map(function (t) {
      var col = VICTORY_COL[t];
      return {
        type: "bar",
        name: t,
        x: civs,
        y: d.civRows.map(function (c) {
          var g = c.row.count_games || 0;
          return g ? (c.row[col] || 0) / g : 0;
        }),
        // Raw win count backing each block, shown as the "n=…" tooltip line.
        customdata: d.civRows.map(function (c) {
          return c.row[col] || 0;
        }),
        marker: { color: VICTORY_COLORS[t] || "#888888", line: { color: BG, width: 0.5 } },
        hovertemplate:
          "%{x}<br>" + t + ": %{y:.1%}<br>n=%{customdata}<extra></extra>",
      };
    });

    // Total win-rate label above each civ's stack.
    var annotations = d.civRows.map(function (c) {
      return {
        x: c.civ,
        y: c.total,
        text: (c.total * 100).toFixed(0) + "%",
        showarrow: false,
        yanchor: "bottom",
        yshift: 2,
        font: { color: TEXT, size: 10 },
      };
    });
    // Average win-rate reference label (top-right, over the dashed line).
    annotations.push({
      xref: "paper",
      x: 1,
      y: d.avg,
      yref: "y",
      text: "average win rate (" + (d.avg * 100).toFixed(1) + "%)",
      showarrow: false,
      xanchor: "right",
      yanchor: "bottom",
      font: { color: TEXT_DIM, size: 12 },
    });

    var layout = {
      title: {
        text: "Win Rate By Civilization",
        font: { color: TEXT, size: 17 },
        x: 0,
        xanchor: "left",
      },
      barmode: "stack",
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 55, r: 20, t: 70, b: 110 },
      font: { color: TEXT_DIM, size: 11 },
      legend: {
        orientation: "h",
        x: 0.5,
        xanchor: "center",
        y: 1.12,
        font: { color: TEXT },
        title: { text: "Victory type", font: { color: TEXT } },
      },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: civs,
        tickangle: -45,
        tickfont: { color: TEXT_DIM, size: 10 },
      },
      yaxis: {
        title: { text: "Winrate", font: { color: TEXT_DIM } },
        tickformat: ".0%",
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      shapes: [
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: "y",
          y0: d.avg,
          y1: d.avg,
          line: { color: TEXT, width: 1.5, dash: "dash" },
        },
      ],
      annotations: annotations,
    };
    Plotly.react(document.getElementById("civs-winrate"), traces, layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Row 4 — full per-civ stats table
  // -------------------------------------------------------------------------
  function prettyHeader(col) {
    if (col === "count_games") return "# Games";
    return col
      .split("_")
      .map(function (w) {
        if (w === "pct") return "%";
        if (w === "avg") return "Avg";
        return w.charAt(0).toUpperCase() + w.slice(1);
      })
      .join(" ");
  }

  // Integer-valued columns: the game count and the raw victory counts (but not
  // the pct_* shares, which stay 2-dp).
  function isIntCol(col) {
    return col === "count_games" || (/_victories$/.test(col) && !/^pct_/.test(col));
  }

  function fmtCell(v, col) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") {
      if (isNaN(v)) return "—";
      return isIntCol(col) ? String(Math.round(v)) : v.toFixed(2);
    }
    return String(v);
  }

  function renderTable() {
    var host = document.getElementById("civs-table");
    host.innerHTML = "";
    // Drop the per-type "% Victories" share columns (pct_*_victories); the raw
    // victory counts and win rate remain.
    var cols = P.table.columns.filter(function (c) {
      return !/^pct_.*_victories$/.test(c);
    });

    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    cols.forEach(function (c) {
      var th = document.createElement("th");
      th.textContent = prettyHeader(c);
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    P.table.rows.forEach(function (r) {
      var tr = document.createElement("tr");
      cols.forEach(function (c) {
        var td = document.createElement("td");
        td.textContent = fmtCell(r[c], c);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  // -------------------------------------------------------------------------
  // render() re-lays out the Plotly charts (responsive to width changes). KPI
  // cards and the table are static, built once at init.
  // -------------------------------------------------------------------------
  function render() {
    renderDonut();
    renderViolin();
    renderWinrate();
  }

  buildKpis();
  renderTable();
  render();

  window.CivsReport = { render: render };
})();
