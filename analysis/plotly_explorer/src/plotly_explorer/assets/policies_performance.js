/* Policies Performance report — a fixed dashboard (no controls), modeled on
   assets/religion_performance.js.

   Sections, top to bottom:
     1. Branch Opens by Civilization — green-shaded table (civ rows x branch cols).
     2. Total Branch Opens — marginal vertical bar of opens per branch.
     3. Wins by Policy Branch — vertical stacked bar, stacked by victory type.
     4. Win Rate by Policy Branch — same layout, each stack is wins/opens. */
(function () {
  "use strict";

  var P = window.PAYLOAD.policies_performance;

  var BG = "#0e1117";
  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";
  var GRID = "rgba(255,255,255,0.07)";

  // Victory-type stack colors (copied from civs.js; they aren't global there).
  var VICTORY_COLORS = {
    Cultural: "#E700E7",
    Science: "#86f9fe",
    Domination: "#B22222",
    Diplomatic: "#6600cc",
  };

  var PLOT_CONFIG = { displayModeBar: false };

  // Visible content size of a plot host, or null when it's hidden (clientWidth 0,
  // e.g. this report isn't the active one). Reading clientWidth forces a
  // synchronous reflow, so it is reliable the moment the report is shown.
  function hostSize(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var w = el.clientWidth;
    return w > 0 ? { el: el, w: w, h: el.clientHeight } : null;
  }

  // -------------------------------------------------------------------------
  // Section 1 — Branch Opens by Civilization (shaded HTML table)
  // -------------------------------------------------------------------------
  // Cell background is a green whose intensity tracks the open count relative to
  // the table-wide max (sqrt-scaled so mid values stay visible), reproducing the
  // mockup's heatmap shading.
  function shade(value, max) {
    if (!max || value <= 0) return "transparent";
    var t = Math.sqrt(value / max); // lift mid-range counts out of the floor
    var lo = [16, 40, 28]; // dark green (near the panel background)
    var hi = [46, 170, 90]; // vivid green for the busiest cells
    var r = Math.round(lo[0] + (hi[0] - lo[0]) * t);
    var g = Math.round(lo[1] + (hi[1] - lo[1]) * t);
    var b = Math.round(lo[2] + (hi[2] - lo[2]) * t);
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function renderOpensTable() {
    var host = document.getElementById("policies-opens-table");
    if (!host) return;
    host.textContent = "";

    var branches = P.branches || [];
    var civs = P.civs || [];
    var opens = P.opens || {};

    // Table-wide max open count for the shading scale.
    var max = 0;
    civs.forEach(function (civ) {
      var row = opens[civ] || {};
      branches.forEach(function (b) {
        var v = row[b] || 0;
        if (v > max) max = v;
      });
    });

    var table = document.createElement("table");

    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    var corner = document.createElement("th");
    corner.textContent = "Civilization";
    htr.appendChild(corner);
    branches.forEach(function (b) {
      var th = document.createElement("th");
      th.className = "policies-branch-col";
      var label = document.createElement("span");
      label.className = "policies-branch-label";
      label.textContent = b;
      th.appendChild(label);
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    civs.forEach(function (civ) {
      var row = opens[civ] || {};
      var tr = document.createElement("tr");
      var name = document.createElement("td");
      name.textContent = civ;
      name.className = "policies-civ-name";
      tr.appendChild(name);
      branches.forEach(function (b) {
        var v = row[b] || 0;
        var td = document.createElement("td");
        td.textContent = v;
        td.style.background = shade(v, max);
        td.style.color = v > 0 ? TEXT : TEXT_DIM;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  // -------------------------------------------------------------------------
  // Section 2 — Total Branch Opens (marginal vertical bar)
  // -------------------------------------------------------------------------
  function renderMarginal() {
    var s = hostSize("policies-marginal");
    if (!s) return;
    var branches = P.branches || [];
    var totals = P.totalOpens || {};
    var counts = branches.map(function (b) {
      return totals[b] || 0;
    });

    var traces = [
      {
        type: "bar",
        x: branches,
        y: counts,
        marker: { color: "#2e9e4f", line: { color: BG, width: 0.5 } },
        text: counts.map(function (c) {
          return c.toLocaleString();
        }),
        textposition: "outside",
        textfont: { color: TEXT, size: 11 },
        cliponaxis: false,
        hovertemplate: "%{x}<br>Opens: %{y}<extra></extra>",
      },
    ];

    var layout = {
      title: { text: "Total Branch Opens", font: { color: TEXT, size: 18 }, x: 0, xanchor: "left" },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 55, r: 20, t: 55, b: 80 },
      font: { color: TEXT_DIM, size: 11 },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: branches,
        tickfont: { color: TEXT, size: 11 },
        tickangle: -45,
      },
      yaxis: {
        title: { text: "Opens", font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      width: s.w,
      height: s.h,
      autosize: false,
    };
    Plotly.react(s.el, traces, layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Sections 3-4 — vertical stacked bars by victory type
  // -------------------------------------------------------------------------
  // valueOf(branch, victoryType) -> numeric height; total(branch) -> stack total
  // label. showLegend puts the shared victory-type key under the last chart only.
  function renderStack(hostId, title, yTitle, valueOf, labelOf, opts) {
    var s = hostSize(hostId);
    if (!s) return;
    opts = opts || {};
    var branches = P.branches || [];
    var order = P.victoryOrder || [];

    // Stack Diplomatic at the bottom (mockup order) by adding traces in reverse;
    // legend.traceorder "reversed" (below) restores the canonical Cultural..
    // Diplomatic legend order.
    var traces = order
      .slice()
      .reverse()
      .map(function (vt) {
        return {
          type: "bar",
          name: vt,
          x: branches,
          y: branches.map(function (b) {
            return valueOf(b, vt);
          }),
          marker: { color: VICTORY_COLORS[vt] || "#888888", line: { color: BG, width: 0.5 } },
          showlegend: !!opts.showLegend,
          hovertemplate: "%{x}<br>" + vt + ": " + (opts.hoverFmt || "%{y}") + "<extra></extra>",
        };
      });

    // Per-branch stack total, drawn above each bar.
    var annotations = branches.map(function (b) {
      var total = 0;
      order.forEach(function (vt) {
        total += valueOf(b, vt);
      });
      return {
        x: b,
        y: total,
        text: labelOf(total),
        showarrow: false,
        yanchor: "bottom",
        yshift: 4,
        font: { color: TEXT, size: 11 },
      };
    });

    // Avg-winrate reference line (Win Rate chart only), same computation and
    // annotation style as the Overview report's Win Rate By Civilization chart
    // (see civs.js renderWinrate), styled as a dotted line here.
    var shapes;
    if (typeof opts.avgLine === "number") {
      shapes = [
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: "y",
          y0: opts.avgLine,
          y1: opts.avgLine,
          line: { color: TEXT, width: 1.5, dash: "dot" },
        },
      ];
      annotations.push({
        xref: "paper",
        x: 1,
        y: opts.avgLine,
        yref: "y",
        text: "Avg Winrate (" + (opts.avgLine * 100).toFixed(1) + "%)",
        showarrow: false,
        xanchor: "right",
        yanchor: "bottom",
        font: { color: TEXT_DIM, size: 12 },
      });
    }

    var layout = {
      title: { text: title, font: { color: TEXT, size: 18 }, x: 0, xanchor: "left" },
      barmode: "stack",
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 55, r: 20, t: 55, b: opts.showLegend ? 120 : 90 },
      font: { color: TEXT_DIM, size: 11 },
      legend: {
        orientation: "h",
        traceorder: "reversed",
        x: 0.5,
        xanchor: "center",
        y: -0.28,
        yanchor: "top",
        title: { text: "Victory type", font: { color: TEXT_DIM } },
        font: { color: TEXT },
      },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: branches,
        tickfont: { color: TEXT, size: 11 },
        tickangle: -45,
      },
      yaxis: {
        title: { text: yTitle, font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
        tickformat: opts.tickformat,
      },
      shapes: shapes,
      annotations: annotations,
      width: s.w,
      height: s.h,
      autosize: false,
    };
    Plotly.react(s.el, traces, layout, PLOT_CONFIG);
  }

  function renderWins() {
    var wins = P.wins || {};
    renderStack(
      "policies-wins",
      "Wins by Policy Branch",
      "Wins",
      function (b, vt) {
        return (wins[b] && wins[b][vt]) || 0;
      },
      function (total) {
        return total.toLocaleString();
      },
      { showLegend: false }
    );
  }

  function renderWinRate() {
    var winrate = P.winrate || {};
    renderStack(
      "policies-winrate",
      "Win Rate by Policy Branch",
      "Win rate",
      function (b, vt) {
        return (winrate[b] && winrate[b][vt]) || 0;
      },
      function (total) {
        return Math.round(total * 100) + "%";
      },
      {
        showLegend: true,
        tickformat: ".0%",
        hoverFmt: "%{y:.1%}",
        avgLine: typeof P.avgWinrate === "number" ? P.avgWinrate : undefined,
      }
    );
  }

  // -------------------------------------------------------------------------
  // render() rebuilds every section. Charts sized while the report is hidden
  // must reflow when it becomes visible; the switcher calls this each time the
  // report is shown.
  // -------------------------------------------------------------------------
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });

  function render() {
    renderOpensTable();
    renderMarginal();
    renderWins();
    renderWinRate();
  }

  render();

  window.PoliciesPerformanceReport = { render: render };
})();
