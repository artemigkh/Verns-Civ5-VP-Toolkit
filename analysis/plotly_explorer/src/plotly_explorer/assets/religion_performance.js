/* Religion Performance report — a fixed dashboard (no controls), modeled on
   assets/civs.js.

   Sections, top to bottom:
     1. Religion Attainment Times — KDE curves of pantheon/founded/enhanced/
        reformed turns, with mean (solid) + median (dashed) vertical lines.
     2. Pantheon Pick Frequency And Performance — horizontal wins/losses stack.
     3. Founders + Followers @ Found — two side-by-side stacks.
     4. Enhancers + Followers @ Enhance — two side-by-side stacks.
     5. Reformation Beliefs — horizontal wins/losses stack.

   Every bar is stacked Losses (red) + Wins (green), labeled "count (winrate%)". */
(function () {
  "use strict";

  var P = window.PAYLOAD.religion_performance;

  var BG = "#0e1117";
  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";
  var GRID = "rgba(255,255,255,0.07)";

  // KDE line color per attainment milestone (matches the reference mockup).
  var EVENT_COLORS = {
    "Pantheon Founded": "#4c9be8",
    "Religion Founded": "#e2402f",
    "Religion Enhanced": "#e8912a",
    "Religion Reformed": "#3fae54",
  };

  // Wins/losses stack colors, shared by every bar chart.
  var LOSS_COLOR = "#cc1f1f";
  var WIN_COLOR = "#2e9e4f";

  // responsive:true is intentionally omitted — its window-resize path routes
  // through Plotly.Plots.resize, which mis-measures these tall containers here.
  // fitWidths() (below) sizes every plot deterministically instead.
  var PLOT_CONFIG = { displayModeBar: false };

  // -------------------------------------------------------------------------
  // Section 1 — Religion Attainment Times (KDE)
  // -------------------------------------------------------------------------
  // A mean/median reference line, drawn as a scatter trace (rather than a layout
  // shape) so it is hoverable: the tooltip reports the average turn to 2 dp. The
  // line spans from 0 up to yMax (the tallest KDE peak) so it covers the plot.
  // It is densely sampled along its height so "closest" hover triggers anywhere
  // on the line, not just near its two endpoints.
  function refLine(event, label, value, yMax, color, dash) {
    var steps = 60;
    var xs = [];
    var ys = [];
    for (var i = 0; i <= steps; i++) {
      xs.push(value);
      ys.push((yMax * i) / steps);
    }
    return {
      type: "scatter",
      mode: "lines",
      x: xs,
      y: ys,
      line: { color: color, width: 1.5, dash: dash },
      showlegend: false,
      hovertemplate: event + "<br>" + label + " turn: " + value.toFixed(2) + "<extra></extra>",
    };
  }

  // A data-less trace used purely to add a line-style key (Mean/Median) to the
  // legend without drawing anything on the plot.
  function styleKey(name, dash) {
    return {
      type: "scatter",
      mode: "lines",
      name: name,
      x: [null],
      y: [null],
      line: { color: TEXT_DIM, width: 1.5, dash: dash },
      hoverinfo: "skip",
      showlegend: true,
    };
  }

  // Visible content size of a plot host, or null when it's hidden (clientWidth 0,
  // e.g. this report isn't the active one). Reading clientWidth forces a
  // synchronous reflow, so it is reliable the moment the report is shown.
  function hostSize(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var w = el.clientWidth;
    return w > 0 ? { el: el, w: w, h: el.clientHeight } : null;
  }

  function renderKDE() {
    var s = hostSize("relperf-kde");
    if (!s) return;
    var traces = [];

    // Tallest KDE peak across all curves — mean/median reference lines are drawn
    // up to this height so they span the meaningful area of the plot.
    var yMax = 0;
    P.eventOrder.forEach(function (ev) {
      var d = P.kde[ev];
      if (d) {
        d.density.forEach(function (v) {
          if (v > yMax) yMax = v;
        });
      }
    });

    P.eventOrder.forEach(function (ev) {
      var d = P.kde[ev];
      if (!d) return;
      var color = EVENT_COLORS[ev] || "#888888";
      traces.push({
        type: "scatter",
        mode: "lines",
        name: ev,
        x: d.x,
        y: d.density,
        line: { color: color, width: 2.5 },
        hovertemplate: ev + "<br>Turn %{x:.0f}<br>density %{y:.4f}<extra></extra>",
      });
      if (typeof d.mean === "number") {
        traces.push(refLine(ev, "Mean", d.mean, yMax, color, "solid"));
      }
      if (typeof d.median === "number") {
        traces.push(refLine(ev, "Median", d.median, yMax, color, "dash"));
      }
    });
    // Style keys for the vertical reference lines.
    traces.push(styleKey("Mean", "solid"));
    traces.push(styleKey("Median", "dash"));

    var layout = {
      title: {
        text: "Religion Attainment Times",
        font: { color: TEXT, size: 20 },
        x: 0,
        xanchor: "left",
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 60, r: 30, t: 60, b: 50 },
      font: { color: TEXT_DIM, size: 12 },
      hovermode: "closest",
      legend: { font: { color: TEXT }, bgcolor: "rgba(0,0,0,0)" },
      xaxis: {
        title: { text: "Turn", font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      yaxis: {
        title: { text: "Density", font: { color: TEXT_DIM } },
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
  // Sections 2-5 — horizontal stacked Losses/Wins bars
  // -------------------------------------------------------------------------
  function renderBar(hostId, title, rows) {
    var host = document.getElementById(hostId);
    if (!host) return;
    rows = rows || [];
    if (!rows.length) {
      Plotly.purge(host);
      host.textContent = "No data.";
      return;
    }
    // Hidden (this report isn't active): render on show instead of at 0 width.
    if (!host.clientWidth) return;

    var beliefs = rows.map(function (r) {
      return r.belief;
    });

    var traces = [
      {
        type: "bar",
        orientation: "h",
        name: "Losses",
        y: beliefs,
        x: rows.map(function (r) {
          return r.losses;
        }),
        marker: { color: LOSS_COLOR, line: { color: BG, width: 0.5 } },
        hovertemplate: "%{y}<br>Losses: %{x}<extra></extra>",
      },
      {
        type: "bar",
        orientation: "h",
        name: "Wins",
        y: beliefs,
        x: rows.map(function (r) {
          return r.wins;
        }),
        marker: { color: WIN_COLOR, line: { color: BG, width: 0.5 } },
        hovertemplate: "%{y}<br>Wins: %{x}<extra></extra>",
      },
    ];

    // End-of-bar "count (winrate%)" label per belief.
    var annotations = rows.map(function (r) {
      return {
        x: r.chosen,
        y: r.belief,
        text: r.chosen.toLocaleString() + "  (" + r.winrate + "%)",
        showarrow: false,
        xanchor: "left",
        xshift: 6,
        font: { color: TEXT, size: 12 },
      };
    });

    var layout = {
      title: {
        text: title,
        font: { color: TEXT, size: 18 },
        x: 0,
        xanchor: "left",
      },
      barmode: "stack",
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 170, r: 90, t: 70, b: 45 },
      font: { color: TEXT_DIM, size: 11 },
      legend: {
        orientation: "h",
        x: 0.5,
        xanchor: "center",
        y: 1.08,
        font: { color: TEXT },
      },
      xaxis: {
        title: { text: "Times chosen", font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      yaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: beliefs,
        // rows arrive sorted by frequency descending; reverse the axis so the
        // most-chosen belief sits at the top (as in the mockups).
        autorange: "reversed",
        automargin: true,
        tickfont: { color: TEXT, size: 12 },
        // Space between the belief labels and the bars so text doesn't touch
        // the axis line.
        ticklen: 10,
        tickcolor: "rgba(0,0,0,0)",
      },
      annotations: annotations,
      width: host.clientWidth,
      height: host.clientHeight,
      autosize: false,
    };
    Plotly.react(host, traces, layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // render() re-lays out every Plotly chart. Charts sized while the report is
  // hidden must reflow when it becomes visible (same reason CivsReport.render
  // exists); the switcher calls this each time the report is shown.
  // -------------------------------------------------------------------------
  // Re-render on window resize so the charts track their container width
  // (responsive:true is omitted — its resize path mis-measures these tall pages).
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });

  function render() {
    var picks = P.picks || {};
    renderKDE();
    renderBar("relperf-pantheon", "Pantheon Pick Frequency And Performance", picks.pantheon);
    renderBar("relperf-founders", "Founders - Pick Frequency and Performance", picks.founder);
    renderBar(
      "relperf-followers-found",
      "Follower Beliefs at Found Time - Pick Frequency and Performance",
      picks.follower_found
    );
    renderBar("relperf-enhancers", "Enhancers - Pick Frequency and Performance", picks.enhancer);
    renderBar(
      "relperf-followers-enhance",
      "Follower Beliefs at Enhance Time - Pick Frequency and Performance",
      picks.follower_enhance
    );
    renderBar(
      "relperf-reformation",
      "Reformation Beliefs - Frequency And Performance",
      picks.reformation
    );
  }

  render();

  window.ReligionPerformanceReport = { render: render };
})();
