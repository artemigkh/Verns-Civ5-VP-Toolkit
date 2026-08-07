/* Wonders report — two charts over a client-side-filtered fact table.

   Sections, top to bottom:
     1. Avg Wonders Built per Game by Civ & Era — horizontal stacked bars, one
        segment per wonder unlock era, civs ordered by total, total at bar end.
     2. Wonder Completion Turn Distributions — ridgeline (KDE) of completion turn
        per wonder, one facet per era, three facets per row.

   Unlike the other reports this one is handed facts, not summaries: the payload
   is the raw list of wonder completions plus the (game, civ) pairs that played,
   and everything on screen — the per-civ averages, the KDE curves, the facet
   windows — is computed here. That is what makes the two filters possible;
   precomputing them server-side would take a curve set per (civ x branch
   subset), i.e. 44 x 2^12 of them.

     * Civilization (single-select) highlights that civ's bar row and restricts
       the ridgelines to its completions. It does not change the bars.
     * Policy Branch (multi-select) picks a cohort of (game, civ) pairs — those
       that opened ANY selected branch at any point in that game — and both
       charts are recomputed over it, denominators included.

   Plotly has no ridgeline primitive, so each ridge is a closed polygon (the KDE
   curve, offset to its row, then back along its baseline) filled with a
   horizontal gradient spanning the whole turn range — the same construction as
   the R prototype's geom_density_ridges_gradient. */
(function () {
  "use strict";

  var P = window.PAYLOAD.wonders;

  var BG = "#0e1117";
  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";
  var GRID = "rgba(255,255,255,0.07)";
  var ACCENT = "#5aa9e6";

  // responsive:true is intentionally omitted — its window-resize path routes
  // through Plotly.Plots.resize, which mis-measures these tall containers
  // (same reasoning as religion_performance.js). Sizes are set explicitly.
  var PLOT_CONFIG = { displayModeBar: false };

  // How many y-units the tallest ridge in a facet spans. The R prototype used
  // scale = 2.0; slightly less overlap reads better at these facet heights.
  var RIDGE_SCALE = 1.8;

  // Plotly's Inferno stops — the colormap the era palette is sampled from, used
  // here as the ridges' fill gradient so a wonder's color tracks its turn.
  var INFERNO = [
    [0.0, "#000004"], [0.111, "#1b0c41"], [0.222, "#4a0c6b"], [0.333, "#781c6d"],
    [0.444, "#a52c60"], [0.556, "#cf4446"], [0.667, "#ed6925"], [0.778, "#fb9b06"],
    [0.889, "#f7d13d"], [1.0, "#fcffa4"],
  ];

  // KDE parameters, ported from the aggregator that used to do this server-side
  // so the unfiltered view is unchanged: points on each facet's shared grid, the
  // resolution of the throwaway probe grid that finds the facet window, and the
  // fraction of a ridge's own peak below which it isn't drawn (ggridges'
  // rel_min_height).
  var KDE_GRID_POINTS = 200;
  var RANGE_PROBE_POINTS = 600;
  var RIDGE_MIN_REL_HEIGHT = 0.01;

  // Fewer samples than this and a density is meaningless, so the ridge is
  // dropped (gaussian_kde is singular below 2 points, or at zero variance).
  var MIN_KDE_SAMPLES = 2;

  var SQRT_2PI = Math.sqrt(2 * Math.PI);

  // How many bandwidths away a sample still contributes to a grid point. At 8
  // the dropped term is exp(-32) ~ 1e-14, below double precision, so this is a
  // pure speedup rather than an approximation.
  var KDE_CUTOFF = 8;

  // Vertical bands of the by-civ chart, in pixels from the top of the figure.
  // That chart's height grows with the civ count, but Plotly places the title
  // and legend in *fractions* of the figure — so a fraction that clears the
  // title at 12 civs sits hundreds of pixels lower at 43. Everything below is
  // expressed in pixels against the height we actually render at (see
  // `fromTop`), which makes the band identical at any row count.
  var BAND = {
    title: 16, // title top
    legend: 52, // legend top — below the title, still above the plot area
    plot: 100, // plot area top, i.e. margin.t
    axis: 50, // x axis + label below the plot area, i.e. margin.b
  };

  // A pixel offset from the top of the figure as the container-relative
  // fraction Plotly wants. Only meaningful with `yref: "container"`, and only
  // when `height` is the height the figure is actually laid out at.
  function fromTop(px, height) {
    return 1 - px / height;
  }

  var state = {
    civ: null, // null = all civilizations
    branches: new Set(), // empty = no branch constraint
  };

  // Cached derived data. computeView() is the only thing that reads the facts;
  // the draw functions only lay out. That keeps the KDE off the resize and
  // report-switch paths, which re-draw what has already been computed.
  var view = null;

  var civIndex = {};
  P.civs.forEach(function (c, i) {
    civIndex[c] = i;
  });

  var eraIndex = {};
  P.eraOrder.forEach(function (e, i) {
    eraIndex[e] = i;
  });

  // Wonder -> index of its unlock era, resolved once: the build scan can't
  // afford a string lookup per row.
  var wonderEra = P.wonders.map(function (w) {
    return eraIndex[w.era];
  });

  // Visible content size of a plot host, or null when it's hidden (clientWidth 0,
  // e.g. this report isn't the active one).
  function hostSize(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var w = el.clientWidth;
    return w > 0 ? { el: el, w: w, h: el.clientHeight } : null;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // -------------------------------------------------------------------------
  // Gaussian KDE — a port of scipy.stats.gaussian_kde's default (Scott) rule,
  // which is what the aggregator used before this moved client-side. Getting the
  // bandwidth wrong would silently reshape every curve, so it is spelled out.
  // -------------------------------------------------------------------------
  // scipy: covariance = var(x, ddof=1) * factor**2 with factor = n**(-1/(d+4))
  // and d = 1, so the kernel's standard deviation is sqrt(var) * n**(-1/5).
  // Returns 0 for a sample with no spread, which the caller reads as "not
  // fittable" — the same case scipy raises a singular-matrix error on.
  function scottBandwidth(samples) {
    var n = samples.length;
    var sum = 0;
    var i;
    for (i = 0; i < n; i++) sum += samples[i];
    var mean = sum / n;
    var ss = 0;
    for (i = 0; i < n; i++) {
      var d = samples[i] - mean;
      ss += d * d;
    }
    var variance = ss / (n - 1); // ddof=1, matching numpy.cov's default
    if (!(variance > 0)) return 0;
    return Math.sqrt(variance) * Math.pow(n, -0.2);
  }

  // Completion turns are integers over a narrow band, so a wonder built 254
  // times lands on far fewer than 254 distinct turns. Collapsing to
  // (value, weight) shrinks the kernel sum by roughly 3x with no approximation:
  // identical samples contribute identical terms.
  function weigh(sorted) {
    var vals = [];
    var wts = [];
    for (var i = 0; i < sorted.length; i++) {
      if (i && sorted[i] === sorted[i - 1]) wts[wts.length - 1]++;
      else {
        vals.push(sorted[i]);
        wts.push(1);
      }
    }
    return { vals: vals, wts: wts, n: sorted.length };
  }

  // Density over an ascending grid. The ascending `vals` let the kernel's window
  // advance monotonically with the grid rather than rescanning every sample per
  // point, so cost tracks the window's width and not the sample count.
  function kdeCurve(pts, bw, grid) {
    var vals = pts.vals;
    var wts = pts.wts;
    var k = vals.length;
    var m = grid.length;
    var out = new Array(m);
    var span = KDE_CUTOFF * bw;
    var norm = 1 / (pts.n * bw * SQRT_2PI);
    var inv = 1 / (2 * bw * bw);
    var lo = 0;
    var hi = 0;
    for (var j = 0; j < m; j++) {
      var x = grid[j];
      while (lo < k && vals[lo] < x - span) lo++;
      while (hi < k && vals[hi] <= x + span) hi++;
      var sum = 0;
      for (var i = lo; i < hi; i++) {
        var d = x - vals[i];
        sum += wts[i] * Math.exp(-d * d * inv);
      }
      out[j] = sum * norm;
    }
    return out;
  }

  function linspace(lo, hi, count) {
    var out = new Array(count);
    var step = (hi - lo) / (count - 1);
    for (var i = 0; i < count; i++) out[i] = lo + step * i;
    out[count - 1] = hi; // don't let the accumulated step drift past the end
    return out;
  }

  // The x-window a facet should span, tails trimmed: the union over its ridges
  // of where each exceeds 1% of its own peak. Without this a single very late
  // completion stretches the whole facet's axis out to its lone hairline tail.
  function eraWindow(curves, lo, hi) {
    var probe = linspace(lo, hi, RANGE_PROBE_POINTS);
    var left = hi;
    var right = lo;
    curves.forEach(function (c) {
      var density = kdeCurve(c.pts, c.bw, probe);
      var peak = 0;
      var i;
      for (i = 0; i < density.length; i++) if (density[i] > peak) peak = density[i];
      var floor = RIDGE_MIN_REL_HEIGHT * peak;
      for (i = 0; i < density.length; i++) {
        if (density[i] >= floor) {
          if (probe[i] < left) left = probe[i];
          if (probe[i] > right) right = probe[i];
        }
      }
    });
    return left >= right ? [lo, hi] : [left, right];
  }

  function median(sorted) {
    var n = sorted.length;
    var mid = n >> 1;
    return n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function average(values) {
    var sum = 0;
    for (var i = 0; i < values.length; i++) sum += values[i];
    return sum / values.length;
  }

  // -------------------------------------------------------------------------
  // computeView — the one pass over the facts, run only when a filter changes
  // -------------------------------------------------------------------------
  function selectedMask() {
    var mask = 0;
    P.branches.forEach(function (b, i) {
      if (state.branches.has(b)) mask |= 1 << i;
    });
    return mask;
  }

  function computeView() {
    var nCivs = P.civs.length;
    var nEras = P.eraOrder.length;
    var nPairs = P.pairCiv.length;
    var mask = selectedMask();
    var i;

    // A (game, civ) pair joins the cohort when it opened any selected branch.
    // No selection means no constraint — the natural default for a cohort
    // filter, unlike the app's other multi-selects where empty matches nothing.
    var pairActive = new Uint8Array(nPairs);
    var gamesByCiv = new Int32Array(nCivs);
    var cohortPairs = 0;
    for (i = 0; i < nPairs; i++) {
      if (mask === 0 || (P.pairMask[i] & mask) !== 0) {
        pairActive[i] = 1;
        gamesByCiv[P.pairCiv[i]]++;
        cohortPairs++;
      }
    }

    // One scan of the builds feeds both charts: the bars count every cohort
    // build (the civ filter only highlights there), while the ridgelines take
    // just the selected civ's.
    var civFilter = state.civ == null ? -1 : civIndex[state.civ];
    var counts = new Int32Array(nCivs * nEras);
    var samples = P.wonders.map(function () {
      return [];
    });
    var cohortBuilds = 0;
    var civBuilds = 0;
    for (i = 0; i < P.buildPair.length; i++) {
      var pair = P.buildPair[i];
      if (!pairActive[pair]) continue;
      var civ = P.pairCiv[pair];
      var wonder = P.buildWonder[i];
      counts[civ * nEras + wonderEra[wonder]]++;
      cohortBuilds++;
      if (civFilter < 0 || civ === civFilter) {
        samples[wonder].push(P.buildTurn[i]);
        civBuilds++;
      }
    }

    return {
      byCiv: buildBarRows(counts, gamesByCiv, nEras),
      facets: buildFacets(samples),
      cohort: {
        pairs: cohortPairs,
        builds: cohortBuilds,
        civPairs: civFilter < 0 ? cohortPairs : gamesByCiv[civFilter],
        civBuilds: civBuilds,
      },
    };
  }

  // Per-civ stacked-bar rows, ordered by total descending. A civ with no cohort
  // games has no denominator, so it is dropped rather than drawn as a zero.
  function buildBarRows(counts, gamesByCiv, nEras) {
    var rows = [];
    for (var civ = 0; civ < P.civs.length; civ++) {
      var games = gamesByCiv[civ];
      if (!games) continue;
      var eras = {};
      var total = 0;
      for (var e = 0; e < nEras; e++) {
        var count = counts[civ * nEras + e];
        if (!count) continue;
        var avg = count / games;
        eras[P.eraOrder[e]] = { avg: avg, count: count };
        total += avg;
      }
      rows.push({ civ: P.civs[civ], games: games, total: total, eras: eras });
    }
    return rows.sort(function (a, b) {
      return b.total - a.total;
    });
  }

  // One entry per era that still has fittable ridges, each with the shared grid
  // its wonders are sampled on. Wonders are ordered by descending median of the
  // *filtered* samples, i.e. bottom-to-top within the facet, so the ordering
  // tracks what is actually on screen.
  function buildFacets(samples) {
    var byEra = P.eraOrder.map(function () {
      return [];
    });
    P.wonders.forEach(function (w, i) {
      var turns = samples[i];
      if (turns.length < MIN_KDE_SAMPLES) return;
      var sorted = turns.slice().sort(function (a, b) {
        return a - b;
      });
      var bw = scottBandwidth(sorted);
      if (!bw) return; // zero variance: every completion landed on one turn
      byEra[wonderEra[i]].push({
        wonder: w.name,
        pts: weigh(sorted),
        lo: sorted[0],
        hi: sorted[sorted.length - 1],
        bw: bw,
        median: median(sorted),
        mean: average(sorted),
        n: sorted.length,
      });
    });

    var facets = [];
    byEra.forEach(function (curves, e) {
      if (!curves.length) return;
      var lo = Infinity;
      var hi = -Infinity;
      curves.forEach(function (c) {
        if (c.lo < lo) lo = c.lo;
        if (c.hi > hi) hi = c.hi;
      });
      var range = eraWindow(curves, lo, hi);
      var grid = linspace(range[0], range[1], KDE_GRID_POINTS);

      curves.sort(function (a, b) {
        return b.median - a.median || (a.wonder < b.wonder ? -1 : 1);
      });
      curves.forEach(function (c) {
        c.density = kdeCurve(c.pts, c.bw, grid);
      });
      facets.push({ era: P.eraOrder[e], x: grid, xRange: range, wonders: curves });
    });
    return facets;
  }

  // -------------------------------------------------------------------------
  // Filter description, shown with each chart so a thinned-out view explains
  // itself rather than looking like missing data.
  // -------------------------------------------------------------------------
  function branchLabel() {
    var picked = P.branches.filter(function (b) {
      return state.branches.has(b);
    });
    return picked.join(" or ");
  }

  // ``scope`` is "civ" for the ridgelines, which the civ filter restricts, and
  // "all" for the bars, where it only highlights.
  function subtitle(scope) {
    var parts = [];
    parts.push(scope === "civ" && state.civ ? state.civ : "All civilizations");
    if (state.branches.size) parts.push("opened " + branchLabel());
    var c = view.cohort;
    var games = scope === "civ" ? c.civPairs : c.pairs;
    var builds = scope === "civ" ? c.civBuilds : c.builds;
    parts.push(
      games.toLocaleString() + " civ-games · " + builds.toLocaleString() + " wonders"
    );
    return parts.join(" — ");
  }

  // -------------------------------------------------------------------------
  // Section 1 — Avg Wonders Built per Game by Civ & Era
  // -------------------------------------------------------------------------
  function drawBar() {
    var host = document.getElementById("wonders-by-civ");
    if (!host) return;
    var rows = view.byCiv;
    if (!rows.length) {
      Plotly.purge(host);
      host.style.height = "";
      host.textContent = "No civilizations opened the selected branches.";
      host.dataset.placeholder = "1";
      return;
    }
    // Clear the placeholder a previous empty render left behind, and only that:
    // blanking textContent on a live plot rips out Plotly's SVG while its
    // internal state survives, so the react() below diffs against a DOM that is
    // gone and paints nothing. The flag is explicit because neither Plotly's
    // class nor its internals distinguish the two states — `purge` leaves
    // `js-plotly-plot` on the node.
    if (host.dataset.placeholder) {
      delete host.dataset.placeholder;
      host.textContent = "";
    }
    // 26px a civ keeps the bars readable at 40+ rows, on top of the header band
    // and the x axis below the plot.
    host.style.height =
      Math.max(400, 26 * rows.length + BAND.plot + BAND.axis) + "px";
    if (!host.clientWidth) return; // hidden: render when the report is shown
    // Measure rather than reuse the number above: `fromTop` is only correct
    // against the height Plotly is given, and that's this one.
    var height = host.clientHeight;

    var civs = rows.map(function (r) {
      return r.civ;
    });

    var traces = P.eraOrder.map(function (era) {
      return {
        type: "bar",
        orientation: "h",
        name: era,
        y: civs,
        x: rows.map(function (r) {
          return (r.eras[era] && r.eras[era].avg) || 0;
        }),
        // The civ name rides in customdata because the y tick labels carry HTML
        // for the highlight, and %{y} would render that markup in the tooltip.
        customdata: rows.map(function (r) {
          return [r.civ, (r.eras[era] && r.eras[era].count) || 0, r.games];
        }),
        marker: { color: P.eraColors[era] || "#888888", line: { color: BG, width: 0.5 } },
        hovertemplate:
          "%{customdata[0]} — " + era +
          "<br>%{x:.2f} per game" +
          "<br>%{customdata[1]} built over %{customdata[2]} games<extra></extra>",
      };
    });

    // Total avg at the end of each civ's stack, emphasized for the selected civ.
    var annotations = rows.map(function (r) {
      var on = r.civ === state.civ;
      return {
        x: r.total,
        y: r.civ,
        text: on ? "<b>" + r.total.toFixed(1) + "</b>" : r.total.toFixed(1),
        showarrow: false,
        xanchor: "left",
        xshift: 6,
        font: { color: on ? ACCENT : TEXT, size: on ? 12 : 11 },
      };
    });

    // A band across the selected civ's row. Category axes accept numeric
    // positions, so the row is addressed by its index in categoryarray.
    var shapes = [];
    var selected = civs.indexOf(state.civ);
    if (selected >= 0) {
      shapes.push({
        type: "rect",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y",
        y0: selected - 0.5,
        y1: selected + 0.5,
        fillcolor: "rgba(90,169,230,0.12)",
        line: { width: 0 },
        layer: "below",
      });
    }

    var layout = {
      title: {
        text: "Avg Wonders Built per Game by Civ & Era",
        font: { color: TEXT, size: 20 },
        x: 0,
        xanchor: "left",
        yref: "container",
        y: fromTop(BAND.title, height),
        yanchor: "top",
      },
      barmode: "stack",
      bargap: 0.28,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 150, r: 60, t: BAND.plot, b: BAND.axis },
      font: { color: TEXT_DIM, size: 11 },
      legend: {
        orientation: "h",
        x: 0.5,
        xanchor: "center",
        yref: "container",
        y: fromTop(BAND.legend, height),
        yanchor: "top",
        // Stacked bars default to a reversed legend; keep the keys in era order
        // so they read left-to-right the same way the segments stack.
        traceorder: "normal",
        font: { color: TEXT, size: 11 },
        title: { text: "Wonder Era", font: { color: TEXT, size: 12 } },
      },
      xaxis: {
        title: { text: "Mean wonders per game", font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      yaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: civs,
        // rows arrive sorted by total descending; reverse the axis so the
        // biggest wonder-builder sits at the top.
        autorange: "reversed",
        automargin: true,
        showgrid: false,
        tickmode: "array",
        tickvals: civs,
        ticktext: civs.map(function (c) {
          return c === state.civ
            ? '<b><span style="color:' + ACCENT + '">' + esc(c) + "</span></b>"
            : esc(c);
        }),
        tickfont: { color: TEXT, size: 11 },
        ticklen: 8,
        tickcolor: "rgba(0,0,0,0)",
      },
      annotations: annotations,
      shapes: shapes,
      width: host.clientWidth,
      height: height,
      autosize: false,
    };
    Plotly.react(host, traces, layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Section 2 — Wonder Completion Turn Distributions (ridgelines per era)
  // -------------------------------------------------------------------------
  // One ridge: the density curve raised to row `index`, closed back along its
  // baseline so `fill: "toself"` shades the area under it. Densities are scaled
  // by the facet's tallest peak, not each wonder's own, so a broad flat
  // distribution stays visibly flatter than a sharp one (as in the R original).
  function ridgeTrace(facet, wonder, index, facetMax) {
    var n = facet.x.length;
    var xs = new Array(2 * n);
    var ys = new Array(2 * n);
    for (var i = 0; i < n; i++) {
      xs[i] = facet.x[i];
      ys[i] = index + (RIDGE_SCALE * wonder.density[i]) / facetMax;
      // Trace the baseline back in reverse to close the polygon.
      xs[n + i] = facet.x[n - 1 - i];
      ys[n + i] = index;
    }
    return {
      type: "scatter",
      mode: "lines",
      x: xs,
      y: ys,
      fill: "toself",
      fillgradient: {
        type: "horizontal",
        colorscale: INFERNO,
        // Data coordinates, spanning every facet rather than this one, so the
        // gradient encodes absolute turn (the R script's shared `limits`).
        start: P.turnRange[0],
        stop: P.turnRange[1],
      },
      line: { color: "rgba(255,255,255,0.30)", width: 0.8 },
      // Hover the filled area as a whole: the vertices themselves are just KDE
      // grid points and baseline padding, so per-point hover is only noise.
      hoveron: "fills",
      text:
        wonder.wonder +
        "<br>median turn " + wonder.median.toFixed(0) +
        "<br>mean turn " + wonder.mean.toFixed(1) +
        "<br>built in " + wonder.n + " games",
      hoverinfo: "text",
      showlegend: false,
    };
  }

  function drawFacet(facet) {
    var s = hostSize("wonders-facet-" + facet.era);
    if (!s) return;

    var wonders = facet.wonders;
    var facetMax = 0;
    wonders.forEach(function (w) {
      w.density.forEach(function (v) {
        if (v > facetMax) facetMax = v;
      });
    });
    if (!facetMax) facetMax = 1;

    // Wonders are ordered by descending median turn, i.e. bottom-to-top. Draw
    // from the top down so each ridge overlaps the one behind it.
    var traces = [];
    for (var i = wonders.length - 1; i >= 0; i--) {
      traces.push(ridgeTrace(facet, wonders[i], i, facetMax));
    }

    var layout = {
      title: {
        text: facet.era,
        font: { color: TEXT, size: 15 },
        x: 0,
        xanchor: "left",
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 10, r: 20, t: 46, b: 38 },
      font: { color: TEXT_DIM, size: 11 },
      hovermode: "closest",
      showlegend: false,
      xaxis: {
        range: facet.xRange,
        gridcolor: GRID,
        zeroline: false,
        tickfont: { color: TEXT_DIM, size: 10 },
      },
      yaxis: {
        tickmode: "array",
        tickvals: wonders.map(function (_, i) {
          return i;
        }),
        ticktext: wonders.map(function (w) {
          return w.wonder;
        }),
        // Room above the top ridge for its own height.
        range: [-0.35, wonders.length - 1 + RIDGE_SCALE + 0.15],
        showgrid: false,
        zeroline: false,
        automargin: true,
        tickfont: { color: TEXT, size: 11 },
        ticklen: 6,
        tickcolor: "rgba(0,0,0,0)",
      },
      width: s.w,
      height: s.h,
      autosize: false,
    };
    Plotly.react(s.el, traces, layout, PLOT_CONFIG);
  }

  // One host div per era, created once. Which of them are shown, and how tall
  // each is, depends on the filter — a civ that never finished a Renaissance
  // wonder has no Renaissance facet — so both are reset on every draw.
  function buildFacetHosts() {
    var grid = document.getElementById("wonders-kde-grid");
    if (!grid || grid.childElementCount) return;
    P.eraOrder.forEach(function (era) {
      var div = document.createElement("div");
      div.id = "wonders-facet-" + era;
      div.className = "wonders-facet";
      grid.appendChild(div);
    });
  }

  function drawFacets() {
    setText("wonders-kde-sub", subtitle("civ"));
    var shown = {};
    view.facets.forEach(function (facet) {
      var el = document.getElementById("wonders-facet-" + facet.era);
      if (!el) return;
      shown[facet.era] = true;
      el.style.display = "";
      // Enough vertical room for every ridge plus the title and x axis.
      el.style.height = Math.max(240, 44 * facet.wonders.length + 90) + "px";
      drawFacet(facet);
    });
    P.eraOrder.forEach(function (era) {
      if (shown[era]) return;
      var el = document.getElementById("wonders-facet-" + era);
      if (!el) return;
      Plotly.purge(el);
      el.style.display = "none";
    });
    var empty = document.getElementById("wonders-kde-empty");
    if (empty) empty.hidden = view.facets.length > 0;
  }

  // -------------------------------------------------------------------------
  // Controls
  // -------------------------------------------------------------------------
  function chip(label, isOn, onClick) {
    var el = document.createElement("div");
    el.className = "chip" + (isOn ? " on" : "");
    el.textContent = label;
    el.addEventListener("click", function () {
      onClick(el);
    });
    return el;
  }

  // Options and the change listener are wired once; the <select> holds its own
  // selection, so unlike the chip groups there is nothing to rebuild.
  function buildCivSelect() {
    var sel = document.getElementById("wonders-civ-select");
    if (!sel) return;
    var all = document.createElement("option");
    all.value = "";
    all.textContent = "All Civilizations";
    sel.appendChild(all);
    P.civs.forEach(function (civ) {
      var opt = document.createElement("option");
      opt.value = civ;
      opt.textContent = civ;
      sel.appendChild(opt);
    });
    sel.value = "";
    sel.addEventListener("change", function () {
      state.civ = sel.value || null;
      scheduleRefresh();
    });
  }

  function buildBranchControls() {
    var host = document.getElementById("wonders-branch-controls");
    if (!host) return;
    host.innerHTML = "";
    P.branches.forEach(function (branch) {
      host.appendChild(
        chip(branch, state.branches.has(branch), function () {
          if (state.branches.has(branch)) state.branches.delete(branch);
          else state.branches.add(branch);
          buildBranchControls();
          scheduleRefresh();
        })
      );
    });
  }

  // -------------------------------------------------------------------------
  // render() re-lays out both charts from the cached view; charts sized while
  // the report was hidden must reflow when it becomes visible, and the switcher
  // calls this on show. refresh() is the filter path, which recomputes first.
  // -------------------------------------------------------------------------
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });

  function draw() {
    drawBar();
    drawFacets();
  }

  function render() {
    if (!view) view = computeView();
    draw();
  }

  function refresh() {
    view = computeView();
    draw();
  }

  // Recomputing the KDEs and redrawing nine figures takes a few hundred ms, all
  // of it in one blocking task. Ending the click's task first lets the control
  // the user just clicked paint its new state, instead of the whole page
  // appearing to freeze and the chip lighting up only once the charts land.
  // A timer rather than requestAnimationFrame: rAF never fires while the tab is
  // hidden, which would strand the filter until the tab was looked at again.
  function scheduleRefresh() {
    setTimeout(refresh, 0);
  }

  buildFacetHosts();
  buildCivSelect();
  buildBranchControls();
  render();

  window.WondersReport = { render: render };
})();
