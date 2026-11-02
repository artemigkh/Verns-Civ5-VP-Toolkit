/* Comparison Overview report — two datasets (A and B) side by side.

   Rows, top to bottom:
     1. KPI pair cards (patch / difficulty / mapscript / size / # games), each
        holding both datasets; a value both share collapses to one line.
     2. Victory Type Share donut for A and for B, same slice order and colours.
     3. Victory Time Spread split violins: A fills the lighter left half of each
        victory type's violin, B the darker right half.
     4. Win rate change per civilization as diverging bars, each side taken
        relative to its own average civ win rate (see renderDelta).
     5. Civilization comparison table: rank in A, rank in B, rank change, then
        the sidebar-chosen metric in A, in B and its change. Sortable like the
        Overview stats table.

   Data. Each dataset's Overview slice (PAYLOAD.civs) is what this report
   compares, so render.py writes every dataset's slice to a small sidecar,
   datasets/<id>.civs.js, which assigns window.EXPLORER_CIVS_SLICES[<id>]. The
   page's own dataset is already in PAYLOAD, and so is any dataset the Dataset
   dropdown has shown since the tab opened (boot.js keeps every full payload in
   window.EXPLORER_PAYLOADS); a side not found in either is loaded by
   <script src> on demand (works over file://, like boot.js). Both caches live
   on window, so they survive the bundle re-run a dataset switch does.

   Victory Time Spread. Below VIOLIN_POINTS_MAX_GAMES combined games each half
   violin carries its per-game beeswarm; above it the points (one hover object
   each) would make the chart lag, so each half gets a median line and dotted
   quartile lines instead, with one hover target at the median that reads out
   the quartiles.

   URL: #Comparison?a=<id>&b=<id>&m=<metric>&s=<col>&sd=a|d. `a` defaults to the
   page's dataset, `b` to the first other dataset in the dropdown. */
(function () {
  "use strict";

  var KEY = "comparison";
  var Router = Explorer.Router;
  var Ser = Explorer.Ser;

  var M = window.EXPLORER_DATASETS || { "default": "", dir: "datasets", list: [] };
  var CURRENT = (window.PAYLOAD && window.PAYLOAD.dataset) || M["default"];
  var IDS = M.list.map(function (d) {
    return d.id;
  });

  // Dataset id -> its Overview slice (null when the dataset lacks the report);
  // an id that is not an own property has not been loaded yet.
  var SLICES = (window.EXPLORER_CIVS_SLICES = window.EXPLORER_CIVS_SLICES || {});
  SLICES[CURRENT] = (window.PAYLOAD && window.PAYLOAD.civs) || null;

  // A dataset whose full payload boot.js already holds needs no .civs.js.
  function sliceFromPayload(id) {
    if (hasOwn(SLICES, id)) return;
    var DS = window.Explorer.Datasets;
    var p = DS && DS.payload(id);
    if (p) SLICES[id] = p.civs || null;
  }
  var FAILED = {}; // id -> true when its sidecar could not be loaded
  var PENDING = {}; // id -> callbacks waiting on its sidecar

  function hasOwn(o, k) {
    return Object.prototype.hasOwnProperty.call(o, k);
  }

  function manifestLabel(id) {
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) return M.list[i].label;
    return id;
  }

  // Load a dataset's Overview slice, then call done(). Synchronous when it is
  // already here; otherwise the sidecar loads once and every waiter runs.
  function ensureSlice(id, done) {
    sliceFromPayload(id);
    if (hasOwn(SLICES, id) || FAILED[id]) return done();
    if (PENDING[id]) return PENDING[id].push(done);
    PENDING[id] = [done];
    function flush() {
      var waiters = PENDING[id] || [];
      delete PENDING[id];
      waiters.forEach(function (fn) {
        fn();
      });
    }
    var script = document.createElement("script");
    script.src = M.dir + "/" + encodeURIComponent(id) + ".civs.js";
    script.onload = function () {
      if (!hasOwn(SLICES, id)) FAILED[id] = true;
      flush();
    };
    script.onerror = function () {
      FAILED[id] = true;
      flush();
    };
    document.head.appendChild(script);
  }

  // -------------------------------------------------------------------------
  // State + URL contract
  // -------------------------------------------------------------------------
  var METRICS = [
    { key: "winrate", label: "Winrate", fmt: pct1, dfmt: pctDelta, higher: true },
    { key: "avg_score", label: "Avg Score", fmt: int, dfmt: intDelta, higher: true },
    { key: "avg_rank_at_game_end", label: "Rank at Game End", fmt: fix2, dfmt: fix2Delta, higher: false },
    { key: "avg_tiles_owned_percentage", label: "Tiles Owned", fmt: pct1, dfmt: pctDelta, higher: true },
    { key: "avg_cities_owned_percentage", label: "Cities Owned", fmt: pct1, dfmt: pctDelta, higher: true },
  ];
  var METRIC_KEYS = METRICS.map(function (m) {
    return m.key;
  });
  // Rank is always shown; its change is A - B (places gained), unlike every
  // other change, which is B - A.
  var RANK = { key: "rank", label: "Rank", fmt: String, dfmt: intDelta, higher: false };

  // Table columns, keyed for the sort param. ra/rb/rd are the rank columns,
  // ma/mb/md the chosen metric's.
  var SORT_COLS = ["civ", "ra", "rb", "rd", "ma", "mb", "md"];

  var DEF = {
    a: CURRENT,
    b: (function () {
      for (var i = 0; i < IDS.length; i++) if (IDS[i] !== CURRENT) return IDS[i];
      return CURRENT;
    })(),
    metric: "winrate",
  };

  var state = {
    a: DEF.a,
    b: DEF.b,
    metric: DEF.metric,
    sortCol: null, // one of SORT_COLS, or null for the default order (rank in A)
    sortDir: null, // 'desc' | 'asc' when sortCol is set
  };

  function encode() {
    var p = {};
    Ser.put(p, "a", state.a, DEF.a);
    Ser.put(p, "b", state.b, DEF.b);
    Ser.put(p, "m", state.metric, DEF.metric);
    if (state.sortCol) {
      p.s = state.sortCol;
      p.sd = state.sortDir === "asc" ? "a" : "d";
    }
    return p;
  }

  function decode(p) {
    state.a = Ser.strIn(p.a, IDS, DEF.a);
    state.b = Ser.strIn(p.b, IDS, DEF.b);
    state.metric = Ser.enumIn(p.m, METRIC_KEYS, DEF.metric);
    state.sortCol = Ser.strIn(p.s, SORT_COLS, null);
    state.sortDir = state.sortCol ? (p.sd === "a" ? "asc" : "desc") : null;
    syncControls();
  }

  // -------------------------------------------------------------------------
  // Formatting
  // -------------------------------------------------------------------------
  function sign(d) {
    return d >= 0 ? "+" : "";
  }
  function pct1(v) {
    return (v * 100).toFixed(1) + "%";
  }
  function pctDelta(d) {
    return sign(d) + (d * 100).toFixed(1) + "%";
  }
  function int(v) {
    return Math.round(v).toLocaleString();
  }
  function intDelta(d) {
    return sign(d) + Math.round(d).toLocaleString();
  }
  function fix2(v) {
    return v.toFixed(2);
  }
  function fix2Delta(d) {
    return sign(d) + d.toFixed(2);
  }
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  // -------------------------------------------------------------------------
  // Palette (civs.js's dark victory palette) and the A/B shades
  // -------------------------------------------------------------------------
  var VICTORY_COLORS = {
    Cultural: "#E700E7",
    Science: "#86f9fe",
    Domination: "#B22222",
    Diplomatic: "#6600cc",
    Time: "#ffffff",
  };
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
  var UP = "#2ea043";
  var DOWN = "#c93c3c";
  var PLOT_CONFIG = { displayModeBar: false, responsive: true };

  function hexToRgb(hex) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgbToHex(rgb) {
    return (
      "#" +
      rgb
        .map(function (v) {
          v = Math.max(0, Math.min(255, Math.round(v)));
          return (v < 16 ? "0" : "") + v.toString(16);
        })
        .join("")
    );
  }
  function rgbToHsl(c) {
    var r = c[0] / 255, g = c[1] / 255, b = c[2] / 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    var h = 0, s = 0, l = (mx + mn) / 2;
    if (mx !== mn) {
      var d = mx - mn;
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      if (mx === r) h = (g - b) / d + (g < b ? 6 : 0);
      else if (mx === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h /= 6;
    }
    return [h, s, l];
  }
  function hslToRgb(h, s, l) {
    function f(p, q, t) {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    }
    if (s === 0) return [l * 255, l * 255, l * 255];
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    var p = 2 * l - q;
    return [f(p, q, h + 1 / 3) * 255, f(p, q, h) * 255, f(p, q, h - 1 / 3) * 255];
  }
  // A gets a lighter tint of the victory colour, B a darker tone. The floors
  // keep Domination and Diplomatic from sinking into the page background.
  function shade(hex, tag) {
    if (hex.toLowerCase() === "#ffffff") return tag === "A" ? "#ffffff" : "#8b97a8";
    var hsl = rgbToHsl(hexToRgb(hex));
    var l = tag === "A" ? Math.min(0.86, hsl[2] + 0.2) : Math.max(0.3, hsl[2] - 0.15);
    return rgbToHex(hslToRgb(hsl[0], hsl[1], l));
  }
  function rgba(hex, a) {
    var c = hexToRgb(hex);
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a + ")";
  }

  // -------------------------------------------------------------------------
  // The two sides
  // -------------------------------------------------------------------------
  // A side is a dataset id plus its loaded slice; `short` names it everywhere
  // the report shows it ("5.4.8 Emperor"), falling back to the dropdown label.
  // A and B stay internal: forum readers took "better in B" for a riddle.
  function side(tag, id) {
    var p = hasOwn(SLICES, id) ? SLICES[id] : null;
    var short = manifestLabel(id);
    if (p && p.kpis) short = String(p.kpis.patch).split(" + ")[0] + " " + p.kpis.difficulty;
    return { tag: tag, id: id, p: p, short: short };
  }

  // Both sides. Two datasets with the same patch and difficulty (5.4.8 and
  // 5.4.8 Neutrals) would be titled alike, so they fall back to the dropdown
  // labels, which are unique.
  function sides() {
    var A = side("A", state.a), B = side("B", state.b);
    if (A.short === B.short) {
      [A, B].forEach(function (s) {
        s.short = manifestLabel(s.id);
      });
    }
    return [A, B];
  }

  function victoryCount(s, t) {
    var i = s.p.victory.present.indexOf(t);
    return i < 0 ? 0 : s.p.victory.counts[i];
  }

  function rowsByCiv(s) {
    var m = {};
    s.p.table.rows.forEach(function (r) {
      m[r.civ] = r;
    });
    return m;
  }

  function metricValue(row, m) {
    if (!row) return null;
    var v = row[m.key];
    return typeof v === "number" && !isNaN(v) ? v : null;
  }

  // -------------------------------------------------------------------------
  // Row 1 — KPI pair cards
  // -------------------------------------------------------------------------
  function buildKpis(A, B) {
    var host = document.getElementById("cmp-kpi-row");
    host.innerHTML = "";
    var ka = A.p.kpis, kb = B.p.kpis;
    [
      { title: "Patch Version", a: ka.patch, b: kb.patch, suffix: true },
      { title: "Difficulty", a: ka.difficulty, b: kb.difficulty },
      { title: "Mapscript", a: ka.mapscript, b: kb.mapscript },
      { title: "Map Size", a: ka.size, b: kb.size },
      { title: "# Games", a: (ka.games || 0).toLocaleString(), b: (kb.games || 0).toLocaleString() },
    ].forEach(function (k) {
      var card = document.createElement("div");
      card.className = "civs-kpi cmp-kpi";
      var body;
      if (k.a === k.b) {
        body = '<div class="cmp-kv one">' + kpiValue(k.a, k.suffix) + '<small>both</small></div>';
      } else {
        body =
          '<div class="cmp-kv"><small>' + esc(A.short) + "</small><span>" + kpiValue(k.a, k.suffix) + "</span></div>" +
          '<div class="cmp-kv"><small>' + esc(B.short) + "</small><span>" + kpiValue(k.b, k.suffix) + "</span></div>";
      }
      card.innerHTML = '<div class="kpi-title">' + esc(k.title) + "</div>" + body;
      host.appendChild(card);
    });
  }

  // "5.4.8 + 5.5.X Tourism + ...": each " + ..." add-on renders smaller, on a
  // line of its own, as on the Overview's patch card.
  function kpiValue(v, suffix) {
    if (!suffix) return esc(v);
    var parts = String(v).split(" + ");
    return (
      esc(parts[0]) +
      parts
        .slice(1)
        .map(function (part) {
          return '<span class="cmp-kv-suffix">+ ' + esc(part) + "</span>";
        })
        .join("")
    );
  }

  // -------------------------------------------------------------------------
  // Row 2 — Victory Type Share donuts, same slice order and colours on both
  // -------------------------------------------------------------------------
  function renderDonut(hostId, s, order) {
    var labels = order.filter(function (t) {
      return victoryCount(s, t) > 0;
    });
    var trace = {
      type: "pie",
      hole: 0.6,
      labels: labels,
      values: labels.map(function (t) {
        return victoryCount(s, t);
      }),
      marker: {
        colors: labels.map(function (t) {
          return VICTORY_COLORS[t] || "#888888";
        }),
        line: { color: BG, width: 2 },
      },
      sort: false,
      direction: "clockwise",
      rotation: 0,
      texttemplate: "<b>%{label}</b><br>%{value}  (%{percent})",
      textposition: "outside",
      outsidetextfont: { color: TEXT, size: 12 },
      hovertemplate: s.short + "<br>%{label}: %{value} (%{percent})<extra></extra>",
    };
    var layout = {
      title: { text: s.short, font: { color: TEXT, size: 16 }, x: 0.5, xanchor: "center" },
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      // Fixed margins: automargin on outside pie labels thrashes on resize.
      margin: { l: 70, r: 70, t: 50, b: 44 },
      font: { color: TEXT },
      annotations: [
        {
          text: "<b>" + (s.p.kpis.games || 0).toLocaleString() + "</b><br>total games",
          showarrow: false,
          font: { color: TEXT, size: 13 },
          x: 0.5,
          y: 0.5,
        },
      ],
    };
    Plotly.react(document.getElementById(hostId), [trace], layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Row 3 — Victory Time Spread, split violins (A left half, B right half)
  // -------------------------------------------------------------------------
  var VIOLIN_TURN_CAP = 500;
  // Combined games (A + B) above which the per-game beeswarm gives way to
  // median and quartile lines: every point is a hover object, and a few
  // thousand of them make hovering lag.
  var VIOLIN_POINTS_MAX_GAMES = 2000;
  // Each violin is 1 category wide (width: 1, scalemode: "width"), so A's half
  // spans [i - HALF, i] and B's [i, i + HALF] around category index i.
  var VIOLIN_HALF = 0.5;

  function violinTrace(s, t, negative, withPoints) {
    var color = shade(VICTORY_COLORS[t] || "#888888", s.tag);
    var turns = s.p.victory.turns[t] || [];
    var victors = (s.p.victory.victors && s.p.victory.victors[t]) || [];
    var trace = {
      type: "violin",
      name: s.short,
      side: negative ? "negative" : "positive",
      x: turns.map(function () {
        return t;
      }),
      y: turns,
      fillcolor: rgba(color, 0.85),
      line: { color: BG, width: 1 },
      width: 1,
      scalemode: "width",
      spanmode: "soft",
      meanline: { visible: false },
      box: { visible: false },
      showlegend: false,
    };
    if (withPoints) {
      trace.customdata = victors;
      trace.points = "all";
      trace.pointpos = negative ? -0.35 : 0.35;
      trace.jitter = 0.3;
      trace.marker = { color: color, size: 4, opacity: 0.9, line: { color: "#000000", width: 0.6 } };
      trace.hoveron = "points";
      trace.hovertemplate = "%{customdata}<br>" + s.short + "<br>" + t + " victory, turn %{y}<extra></extra>";
    } else {
      trace.points = false;
      trace.hoverinfo = "skip"; // the median marker (quartileHover) answers instead
    }
    return trace;
  }

  // Linear-interpolated quantile (R type 7, Plotly's "linear" quartilemethod)
  // of an ascending array.
  function quantile(sorted, q) {
    if (!sorted.length) return null;
    var pos = (sorted.length - 1) * q;
    var lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  function quartiles(turns) {
    var sorted = turns.slice().sort(function (a, b) {
      return a - b;
    });
    return { n: sorted.length, q1: quantile(sorted, 0.25), med: quantile(sorted, 0.5), q3: quantile(sorted, 0.75) };
  }

  // Lines across one half violin: the median solid, the quartiles dotted. The
  // x axis is categorical, so shapes address it by category index; the lines
  // run from the centre seam to the half's outer edge. Dark on A's lighter
  // tint, light on B's darker tone.
  function quartileShapes(s, idx, q) {
    var negative = s.tag === "A";
    var x0 = idx, x1 = negative ? idx - VIOLIN_HALF : idx + VIOLIN_HALF;
    var color = negative ? "rgba(14,17,23,0.9)" : "rgba(215,221,231,0.95)";
    function line(y, dash, width) {
      return {
        type: "line",
        xref: "x",
        yref: "y",
        x0: x0,
        x1: x1,
        y0: y,
        y1: y,
        layer: "above",
        line: { color: color, width: width, dash: dash },
      };
    }
    return [line(q.q1, "dot", 1.2), line(q.q3, "dot", 1.2), line(q.med, "solid", 2)];
  }

  // One invisible marker per half, on the median line, so hovering the half
  // reads out its quartiles. A numeric x on the category axis would become a
  // category of its own, so the marker sits on xaxis2: a hidden linear axis
  // overlaying the category one with the same range, where category i is x=i.
  function quartileHover(s, t, idx, q) {
    var negative = s.tag === "A";
    return {
      type: "scatter",
      mode: "markers",
      xaxis: "x2",
      x: [negative ? idx - VIOLIN_HALF / 2 : idx + VIOLIN_HALF / 2],
      y: [q.med],
      marker: { size: 28, opacity: 0, color: shade(VICTORY_COLORS[t] || "#888888", s.tag) },
      hovertemplate:
        s.short + "<br>" + t + " victory, " + q.n.toLocaleString() + " games" +
        "<br>Q3: turn " + Math.round(q.q3) +
        "<br>median: turn " + Math.round(q.med) +
        "<br>Q1: turn " + Math.round(q.q1) +
        "<extra></extra>",
      showlegend: false,
    };
  }

  function renderViolin(A, B, order) {
    // Time victories always end at the turn limit, so they add no spread.
    var types = order.filter(function (t) {
      return t !== "Time" && victoryCount(A, t) + victoryCount(B, t) > 0;
    });
    var games = (A.p.kpis.games || 0) + (B.p.kpis.games || 0);
    var withPoints = games <= VIOLIN_POINTS_MAX_GAMES;
    var traces = [];
    var shapes = [];
    types.forEach(function (t, idx) {
      [A, B].forEach(function (s) {
        if (!victoryCount(s, t)) return;
        traces.push(violinTrace(s, t, s.tag === "A", withPoints));
        if (withPoints) return;
        var q = quartiles(s.p.victory.turns[t] || []);
        if (!q.n) return;
        shapes = shapes.concat(quartileShapes(s, idx, q));
        traces.push(quartileHover(s, t, idx, q));
      });
    });
    // Category i sits at x=i; the half-violins reach ±VIOLIN_HALF around it.
    var xRange = [-VIOLIN_HALF - 0.1, types.length - 1 + VIOLIN_HALF + 0.1];
    var layout = {
      shapes: shapes,
      hovermode: "closest",
      title: { text: "Victory Time Spread", font: { color: TEXT, size: 17 }, x: 0.5, xanchor: "center" },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 60, r: 20, t: 50, b: 40 },
      font: { color: TEXT_DIM, size: 12 },
      violinmode: "overlay",
      violingap: 0,
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: types,
        range: xRange,
        tickfont: { color: TEXT, size: 13 },
        gridcolor: "rgba(255,255,255,0.04)",
      },
      // Carries the quartile hover markers (see quartileHover); pinned to the
      // category axis's range so x=i is category i on both.
      xaxis2: { overlaying: "x", range: xRange, visible: false, fixedrange: true },
      yaxis: {
        title: { text: "Game-ending turn", font: { color: TEXT_DIM, size: 12 } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.12)",
        autorange: true,
        autorangeoptions: { clipmax: VIOLIN_TURN_CAP },
      },
      showlegend: false,
    };
    Plotly.react(document.getElementById("cmp-violin"), traces, layout, PLOT_CONFIG);
    renderShadeKey(A, B, types, withPoints);
  }

  // Under the violins: which shades are A and which are B, and what the lines
  // mean when the beeswarm is off.
  function renderShadeKey(A, B, types, withPoints) {
    var host = document.getElementById("cmp-violin-key");
    var parts = [A, B].map(function (s) {
      var swatches = types
        .map(function (t) {
          return '<i class="cmp-sw" style="background:' + shade(VICTORY_COLORS[t] || "#888888", s.tag) + '"></i>';
        })
        .join("");
      return "<span>" + swatches + " " + esc(s.short) + (s.tag === "A" ? " (lighter, left)" : " (darker, right)") + "</span>";
    });
    if (!withPoints) {
      parts.push("<span>solid line: median, dotted: quartiles</span>");
    }
    host.innerHTML = parts.join("");
  }

  // -------------------------------------------------------------------------
  // Row 4 — win rate change per civ, relative to each side's average, diverging
  // bars
  // -------------------------------------------------------------------------

  // The average civ's win rate: total wins over total civ-games, i.e. what one
  // seat wins by chance. It falls with the player count (12-civ Huge maps sit
  // near 1/12, 8-civ Standard near 1/8), so a raw B - A would push nearly every
  // civ negative when B seats more players.
  function avgWinrate(s) {
    var wins = 0, games = 0;
    s.p.table.rows.forEach(function (r) {
      var n = r.count_games || 0;
      wins += (r.winrate || 0) * n;
      games += n;
    });
    return games ? wins / games : 0;
  }

  function pp2(d) {
    return sign(d) + d.toFixed(2);
  }

  function renderDelta(A, B) {
    var ra = rowsByCiv(A), rb = rowsByCiv(B);
    var avgA = avgWinrate(A) * 100, avgB = avgWinrate(B) * 100;
    var rows = [];
    Object.keys(ra).forEach(function (civ) {
      if (!rb[civ]) return;
      var a = (ra[civ].winrate || 0) * 100, b = (rb[civ].winrate || 0) * 100;
      rows.push({ civ: civ, a: a, b: b, d: b - avgB - (a - avgA) });
    });
    rows.sort(function (x, y) {
      return y.d - x.d;
    });
    var host = document.getElementById("cmp-delta");
    host.style.height = Math.max(360, rows.length * 20 + 192) + "px";
    var trace = {
      type: "bar",
      orientation: "h",
      y: rows.map(function (r) {
        return r.civ;
      }),
      x: rows.map(function (r) {
        return r.d;
      }),
      marker: {
        color: rows.map(function (r) {
          return r.d >= 0 ? UP : DOWN;
        }),
        line: { color: BG, width: 0.5 },
      },
      text: rows.map(function (r) {
        return sign(r.d) + r.d.toFixed(1);
      }),
      textposition: "outside",
      textfont: { color: TEXT, size: 11 },
      cliponaxis: false,
      customdata: rows.map(function (r) {
        // Pre-formatted: Plotly ignored a %{x:+.2f} format here and printed
        // the raw float.
        return [r.a.toFixed(1), r.b.toFixed(1), pp2(r.a - avgA), pp2(r.b - avgB), pp2(r.d)];
      }),
      hovertemplate:
        "%{y}<br>" + A.short + ": %{customdata[0]}% (%{customdata[2]} pp vs average)<br>" +
        B.short + ": %{customdata[1]}% (%{customdata[3]} pp vs average)<br>change %{customdata[4]} pp<extra></extra>",
    };
    var layout = {
      title: {
        text:
          "Win Rate Change vs Average By Civilization, " + A.short + " → " + B.short +
          '<br><span style="font-size:12px"><span style="color:' + UP + '">■ Green</span>: the civ does better in ' +
          esc(B.short) + " than in " + esc(A.short) + ".</span>" +
          '<br><span style="font-size:12px"><span style="color:' + DOWN + '">■ Red</span>: it does worse in ' +
          esc(B.short) + " than in " + esc(A.short) + ".</span>" +
          '<br><span style="font-size:12px">Each measured from its own average civ win rate: ' +
          avgA.toFixed(1) + "% in " + esc(A.short) + ", " + avgB.toFixed(1) + "% in " + esc(B.short) + "</span>",
        font: { color: TEXT, size: 17 },
        x: 0,
        xanchor: "left",
        // Pinned to the top: Plotly centres a multi-line title in the margin,
        // which would push its last line into the direction labels.
        y: 1,
        yref: "container",
        yanchor: "top",
        pad: { t: 20 },
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 110, r: 50, t: 138, b: 40 },
      font: { color: TEXT_DIM, size: 11 },
      bargap: 0.3,
      // Direction labels either side of the zero line, so the sign reads
      // without the subtitle.
      annotations: [
        { text: "◀ worse in " + esc(B.short), color: DOWN, xanchor: "right", xshift: -6 },
        { text: "better in " + esc(B.short) + " ▶", color: UP, xanchor: "left", xshift: 6 },
      ].map(function (d) {
        return {
          text: "<b>" + d.text + "</b>",
          x: 0,
          xref: "x",
          xanchor: d.xanchor,
          xshift: d.xshift,
          y: 1,
          yref: "paper",
          yanchor: "bottom",
          yshift: 4,
          showarrow: false,
          font: { color: d.color, size: 12 },
        };
      }),
      xaxis: {
        title: { text: "Change in win rate above or below average (percentage points)", font: { color: TEXT_DIM } },
        gridcolor: GRID,
        zerolinecolor: "rgba(255,255,255,0.25)",
      },
      yaxis: { type: "category", autorange: "reversed", tickfont: { color: TEXT, size: 11 } },
    };
    Plotly.react(host, [trace], layout, PLOT_CONFIG);
  }

  // -------------------------------------------------------------------------
  // Row 5 — civilization comparison table
  // -------------------------------------------------------------------------
  function metricDef() {
    for (var i = 0; i < METRICS.length; i++) if (METRICS[i].key === state.metric) return METRICS[i];
    return METRICS[0];
  }

  // One row per civ in either dataset, with both sides' values and the
  // changes. Rank change is A - B (places gained); the metric's is B - A.
  function tableRows(A, B, m) {
    var ra = rowsByCiv(A), rb = rowsByCiv(B);
    var civs = Object.keys(ra);
    Object.keys(rb).forEach(function (c) {
      if (!ra[c]) civs.push(c);
    });
    return civs.map(function (c) {
      var rankA = metricValue(ra[c], RANK), rankB = metricValue(rb[c], RANK);
      var mA = metricValue(ra[c], m), mB = metricValue(rb[c], m);
      return {
        civ: c,
        ra: rankA,
        rb: rankB,
        rd: rankA !== null && rankB !== null ? rankA - rankB : null,
        ma: mA,
        mb: mB,
        md: mA !== null && mB !== null ? mB - mA : null,
      };
    });
  }

  function sortRows(rows) {
    var col = state.sortCol;
    var dir = state.sortDir === "asc" ? 1 : -1;
    rows.sort(function (x, y) {
      var av, bv;
      if (!col) {
        // Default: rank in A ascending; civs absent from A go last.
        av = x.ra === null ? Infinity : x.ra;
        bv = y.ra === null ? Infinity : y.ra;
        return av - bv || String(x.civ).localeCompare(String(y.civ));
      }
      av = x[col];
      bv = y[col];
      if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") return dir * (av - bv);
      return dir * String(av).localeCompare(String(bv));
    });
    return rows;
  }

  // Cycle a column's sort: desc -> asc -> default (clear), as civs.js does.
  function cycleSort(col) {
    if (state.sortCol !== col) {
      state.sortCol = col;
      state.sortDir = "desc";
    } else if (state.sortDir === "desc") {
      state.sortDir = "asc";
    } else {
      state.sortCol = null;
      state.sortDir = null;
    }
    drawnTableKey = null;
    renderTable();
    Router.touch(KEY);
  }

  function valueCell(v, m, groupStart) {
    var cls = (groupStart ? "cmp-gl" : "") + (v === null ? " cmp-dim" : "");
    return '<td class="' + cls + '">' + (v === null ? "—" : m.fmt(v)) + "</td>";
  }

  // Change cell: green when the civ did better in B, red when worse, with the
  // tint and the arrow count scaled to the column's largest change.
  function deltaCell(d, m, maxAbs, isRank) {
    if (d === null) return '<td class="cmp-d cmp-dim">—</td>';
    var z = maxAbs ? Math.abs(d) / maxAbs : 0;
    var arrows = z >= 0.4 ? 2 : z >= 0.05 ? 1 : 0;
    var improved = isRank ? d > 0 : m.higher ? d > 0 : d < 0;
    var cls = "cmp-d" + (arrows ? (improved ? " cmp-up" : " cmp-down") : "");
    var glyph = "";
    for (var i = 0; i < arrows; i++) glyph += d > 0 ? "▲" : "▼";
    var txt = isRank && d === 0 ? "–" : m.dfmt(d);
    return (
      '<td class="' + cls + '" style="--i:' + (0.12 + 0.55 * z).toFixed(2) + '">' +
      txt + (glyph ? '<span class="cmp-arr">' + glyph + "</span>" : "") +
      "</td>"
    );
  }

  var drawnTableKey = null;

  function tableKey() {
    return [state.a, state.b, state.metric, state.sortCol, state.sortDir].join("|");
  }

  function renderTable() {
    var both = sides(), A = both[0], B = both[1];
    if (!A.p || !B.p) return;
    var key = tableKey();
    if (key === drawnTableKey) return;
    drawnTableKey = key;

    var m = metricDef();
    var rows = sortRows(tableRows(A, B, m));
    var maxRank = 0, maxMetric = 0;
    rows.forEach(function (r) {
      if (r.rd !== null) maxRank = Math.max(maxRank, Math.abs(r.rd));
      if (r.md !== null) maxMetric = Math.max(maxMetric, Math.abs(r.md));
    });

    var cols = [
      { key: "civ", label: "Civ" },
      { key: "ra", label: A.short + " Rank", group: true },
      { key: "rb", label: B.short + " Rank" },
      { key: "rd", label: "Rank Change" },
      { key: "ma", label: A.short + " " + m.label, group: true },
      { key: "mb", label: B.short + " " + m.label },
      { key: "md", label: m.label + " Change" },
    ];

    var host = document.getElementById("cmp-table");
    host.innerHTML = "";
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    cols.forEach(function (c) {
      var th = document.createElement("th");
      th.className =
        "civs-sortable" + (state.sortCol === c.key ? " civs-sorted" : "") + (c.group ? " cmp-gl" : "");
      th.appendChild(document.createTextNode(c.label));
      var arrow = document.createElement("span");
      if (state.sortCol === c.key) {
        arrow.className = "civs-sort-arrow";
        arrow.textContent = state.sortDir === "asc" ? "▲" : "▼";
      } else {
        arrow.className = "civs-sort-arrow civs-sort-idle";
        arrow.textContent = "⇅";
      }
      th.appendChild(arrow);
      th.addEventListener("click", function () {
        cycleSort(c.key);
      });
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var html = "";
    rows.forEach(function (r) {
      html +=
        "<tr><td>" + esc(r.civ) + "</td>" +
        valueCell(r.ra, RANK, true) + valueCell(r.rb, RANK) + deltaCell(r.rd, RANK, maxRank, true) +
        valueCell(r.ma, m, true) + valueCell(r.mb, m) + deltaCell(r.md, m, maxMetric, false) +
        "</tr>";
    });
    var tbody = document.createElement("tbody");
    tbody.innerHTML = html;
    table.appendChild(tbody);
    host.appendChild(table);

    document.getElementById("cmp-table-sub").textContent =
      "Rank change is places gained from " + A.short + " to " + B.short +
      "; every other change is " + B.short + " minus " + A.short +
      ". Green means the civ did better in " + B.short + " than in " + A.short + ".";
  }

  // -------------------------------------------------------------------------
  // Controls (left sidebar): the two dataset selects, swap, metric chips
  // -------------------------------------------------------------------------
  function fillSelect(id) {
    var sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = "";
    M.list.forEach(function (d) {
      var opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.label;
      sel.appendChild(opt);
    });
  }

  function chip(label, isOn, onClick) {
    var el = document.createElement("div");
    el.className = "chip" + (isOn ? " on" : "");
    el.textContent = label;
    el.addEventListener("click", onClick);
    return el;
  }

  function syncControls() {
    var selA = document.getElementById("cmp-ds-a");
    var selB = document.getElementById("cmp-ds-b");
    if (selA && selA.value !== state.a) selA.value = state.a;
    if (selB && selB.value !== state.b) selB.value = state.b;
    var host = document.getElementById("cmp-metric-controls");
    if (host) {
      host.innerHTML = "";
      METRICS.forEach(function (m) {
        host.appendChild(
          chip(m.label, state.metric === m.key, function () {
            if (state.metric === m.key) return;
            state.metric = m.key;
            syncControls();
            renderTable();
            Router.touch(KEY);
          })
        );
      });
    }
  }

  function wireControls() {
    fillSelect("cmp-ds-a");
    fillSelect("cmp-ds-b");
    var selA = document.getElementById("cmp-ds-a");
    var selB = document.getElementById("cmp-ds-b");
    if (selA) {
      selA.addEventListener("change", function () {
        state.a = selA.value;
        onSidesChanged();
      });
    }
    if (selB) {
      selB.addEventListener("change", function () {
        state.b = selB.value;
        onSidesChanged();
      });
    }
    var swap = document.getElementById("cmp-swap");
    if (swap) {
      swap.addEventListener("click", function () {
        var a = state.a;
        state.a = state.b;
        state.b = a;
        syncControls();
        onSidesChanged();
      });
    }
  }

  function onSidesChanged() {
    render();
    Router.touch(KEY);
  }

  // -------------------------------------------------------------------------
  // render(): load both slices, then draw everything. Called by the router on
  // show and on every sidebar resize; the charts are responsive, the KPI cards
  // and table rebuild only when what they show changes.
  // -------------------------------------------------------------------------
  var drawnSidesKey = null;
  var renderToken = 0;

  function setNote(text) {
    var note = document.getElementById("cmp-note");
    note.textContent = text || "";
    note.hidden = !text;
    document.getElementById("cmp-body").hidden = !!text;
  }

  function render() {
    var token = ++renderToken;
    syncControls();
    if (M.list.length < 2) {
      return setNote("This build has only one dataset, so there is nothing to compare it with.");
    }
    var waiting = [state.a, state.b].filter(function (id) {
      sliceFromPayload(id);
      return !hasOwn(SLICES, id) && !FAILED[id];
    });
    if (waiting.length) {
      setNote(
        "Loading " +
          waiting
            .map(function (id) {
              return manifestLabel(id);
            })
            .join(" and ") +
          "…"
      );
    }
    ensureSlice(state.a, function () {
      ensureSlice(state.b, function () {
        if (token !== renderToken) return; // a newer render superseded this one
        draw();
      });
    });
  }

  function draw() {
    var both = sides(), A = both[0], B = both[1];
    var missing = [A, B].filter(function (s) {
      return !s.p;
    });
    if (missing.length) {
      return setNote(
        missing
          .map(function (s) {
            return FAILED[s.id]
              ? 'Could not load the "' + manifestLabel(s.id) + '" dataset.'
              : "Overview has no data for the " + manifestLabel(s.id) + " dataset.";
          })
          .join(" ") + " Pick another dataset."
      );
    }
    setNote("");
    var sidesKey = state.a + "|" + state.b;
    if (sidesKey !== drawnSidesKey) {
      drawnSidesKey = sidesKey;
      buildKpis(A, B);
    }
    var order = A.p.victoryOrder || B.p.victoryOrder || Object.keys(VICTORY_COLORS);
    var present = order.filter(function (t) {
      return victoryCount(A, t) + victoryCount(B, t) > 0;
    });
    renderDonut("cmp-donut-a", A, present);
    renderDonut("cmp-donut-b", B, present);
    renderViolin(A, B, order);
    renderDelta(A, B);
    renderTable();
  }

  wireControls();
  syncControls();

  window.ComparisonReport = { render: render };
  Router.register({
    key: KEY,
    slug: "Comparison",
    render: render,
    encode: encode,
    decode: decode,
  });
})();
