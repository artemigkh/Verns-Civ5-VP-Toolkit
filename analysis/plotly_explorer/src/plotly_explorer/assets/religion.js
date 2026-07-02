/* Religion Belief Yield report — client-side reactivity (no backend). */
(function () {
  "use strict";

  var P = window.PAYLOAD.religion;

  // ---------------------------------------------------------------------------
  // Yield color LUT — edit freely. Yields not listed get a stable fallback color.
  // ---------------------------------------------------------------------------
  var YIELD_COLORS = {
    Food: "#3aa655", // green
    Production: "#8b5a2b", // brown
    Gold: "#d4af37", // gold
    Science: "#2f6fed", // blue
    Faith: "#ffffff", // white
    Tourism: "#9aa0a6", // grey
    Culture: "#c724b1", // magenta
  };

  // Deterministic pseudo-random color for unlisted yields (stable across renders).
  function hashColor(name) {
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return "hsl(" + (h % 360) + ", 65%, 55%)";
  }
  var fallbackCache = {};
  function yieldColor(y) {
    if (YIELD_COLORS[y]) return YIELD_COLORS[y];
    if (!fallbackCache[y]) fallbackCache[y] = hashColor(y);
    return fallbackCache[y];
  }

  // Lighten a color toward white (amt in [0,1]) for the Follower segment.
  function lighten(color, amt) {
    var rgb = toRgb(color);
    if (!rgb) return color;
    var r = Math.round(rgb[0] + (255 - rgb[0]) * amt);
    var g = Math.round(rgb[1] + (255 - rgb[1]) * amt);
    var b = Math.round(rgb[2] + (255 - rgb[2]) * amt);
    return "rgb(" + r + "," + g + "," + b + ")";
  }
  function toRgb(color) {
    if (color[0] === "#") {
      var hex = color.slice(1);
      if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      return [
        parseInt(hex.slice(0, 2), 16),
        parseInt(hex.slice(2, 4), 16),
        parseInt(hex.slice(4, 6), 16),
      ];
    }
    var h = color.match(/hsl\(\s*(\d+)\s*,\s*(\d+)%\s*,\s*(\d+)%\s*\)/);
    if (h) return hslToRgb(+h[1], +h[2], +h[3]);
    var r = color.match(/rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/);
    if (r) return [+r[1], +r[2], +r[3]];
    return null;
  }
  function hslToRgb(h, s, l) {
    s /= 100;
    l /= 100;
    var c = (1 - Math.abs(2 * l - 1)) * s;
    var x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    var m = l - c / 2;
    var r = 0,
      g = 0,
      b = 0;
    if (h < 60) {
      r = c;
      g = x;
    } else if (h < 120) {
      r = x;
      g = c;
    } else if (h < 180) {
      g = c;
      b = x;
    } else if (h < 240) {
      g = x;
      b = c;
    } else if (h < 300) {
      r = x;
      b = c;
    } else {
      r = c;
      b = x;
    }
    return [
      Math.round((r + m) * 255),
      Math.round((g + m) * 255),
      Math.round((b + m) * 255),
    ];
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  var state = {
    yields: new Set(), // multi-select; populated below
    metric: "turn", // 'turn' | 'total'
    benefactors: new Set(["owner"]), // 'owner' | 'follower'
    displayEras: new Set(P.defaultDisplayEras),
    types: new Set(P.defaultBeliefTypes), // enabled belief types == sections shown
    topN: 15, // max beliefs shown per facet
    selected: new Set(), // checked beliefs
  };
  if (P.yields.length) state.yields.add(P.yields[0]); // default-select first yield

  var SECTION_LABEL = {
    Pantheon: "Pantheons",
    Founder: "Founder Beliefs",
    Follower: "Follower Beliefs",
    Enhancer: "Enhancer Beliefs",
    Reformation: "Reformation Beliefs",
  };

  // ---------------------------------------------------------------------------
  // Filtering: a belief is eligible if its type is enabled AND it has data for at
  // least one currently-selected yield. Same delta-sync as the building report so
  // toggles auto-(de)select without wiping manual checkbox choices.
  // ---------------------------------------------------------------------------
  function beliefHasSelectedYield(belief) {
    var ys = P.beliefYields[belief] || [];
    for (var i = 0; i < ys.length; i++) if (state.yields.has(ys[i])) return true;
    return false;
  }

  function computeFiltered() {
    var out = new Set();
    state.types.forEach(function (t) {
      (P.beliefsByType[t] || []).forEach(function (b) {
        if (beliefHasSelectedYield(b)) out.add(b);
      });
    });
    return out;
  }

  var prevEligible = new Set();
  function syncSelection() {
    var eligible = computeFiltered();
    state.selected.forEach(function (b) {
      if (!eligible.has(b)) state.selected.delete(b);
    });
    eligible.forEach(function (b) {
      if (!prevEligible.has(b)) state.selected.add(b);
    });
    prevEligible = eligible;
  }

  // ---------------------------------------------------------------------------
  // Control builders
  // ---------------------------------------------------------------------------
  function chip(label, isOn, onClick) {
    var el = document.createElement("div");
    el.className = "chip" + (isOn ? " on" : "");
    el.textContent = label;
    el.addEventListener("click", function () {
      onClick(el);
    });
    return el;
  }

  function buildYieldControls() {
    var host = document.getElementById("rel-yield-controls");
    host.innerHTML = "";
    P.yields.forEach(function (y) {
      host.appendChild(
        chip(y, state.yields.has(y), function () {
          if (state.yields.has(y)) state.yields.delete(y);
          else state.yields.add(y);
          syncSelection();
          buildYieldControls();
          buildBeliefList();
          buildLegend();
          render();
        })
      );
    });
  }

  function buildMetricControls() {
    var host = document.getElementById("rel-metric-controls");
    host.innerHTML = "";
    [
      { key: "turn", label: "Per-Turn Avg" },
      { key: "total", label: "Era Totals" },
    ].forEach(function (o) {
      host.appendChild(
        chip(o.label, state.metric === o.key, function () {
          state.metric = o.key;
          buildMetricControls();
          render();
        })
      );
    });
  }

  function buildBenefactorControls() {
    var host = document.getElementById("rel-benefactor-controls");
    host.innerHTML = "";
    [
      { key: "owner", label: "Owner" },
      { key: "follower", label: "Follower" },
    ].forEach(function (o) {
      host.appendChild(
        chip(o.label, state.benefactors.has(o.key), function () {
          if (state.benefactors.has(o.key)) state.benefactors.delete(o.key);
          else state.benefactors.add(o.key);
          buildBenefactorControls();
          buildLegend();
          render();
        })
      );
    });
  }

  function buildTopNControls() {
    var host = document.getElementById("rel-topn-controls");
    host.innerHTML = "";
    var input = document.createElement("input");
    input.type = "range";
    input.min = "1";
    input.max = "30";
    input.step = "1";
    input.value = state.topN;
    input.className = "slider";
    var value = document.createElement("span");
    value.className = "num-suffix";
    value.textContent = state.topN;
    input.addEventListener("input", function () {
      state.topN = parseInt(input.value, 10);
      value.textContent = state.topN;
      render();
    });
    host.appendChild(input);
    host.appendChild(value);
  }

  function buildDisplayEraControls() {
    var host = document.getElementById("rel-display-era-controls");
    host.innerHTML = "";
    P.eraOrder.forEach(function (era) {
      host.appendChild(
        chip(era, state.displayEras.has(era), function () {
          if (state.displayEras.has(era)) state.displayEras.delete(era);
          else state.displayEras.add(era);
          buildDisplayEraControls();
          render();
        })
      );
    });
  }

  function buildFilterTypeControls() {
    var host = document.getElementById("rel-filter-type-controls");
    host.innerHTML = "";
    P.beliefTypes.forEach(function (t) {
      host.appendChild(
        chip(t, state.types.has(t), function () {
          if (state.types.has(t)) state.types.delete(t);
          else state.types.add(t);
          syncSelection();
          buildFilterTypeControls();
          buildBeliefList();
          render();
        })
      );
    });
  }

  // ---------------------------------------------------------------------------
  // Belief list (right sidebar): 5 sections in fixed order, hidden when their
  // type is toggled off; beliefs A–Z within each section.
  // ---------------------------------------------------------------------------
  function beliefRow(name) {
    var row = document.createElement("label");
    row.className = "b-row";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.selected.has(name);
    cb.addEventListener("change", function () {
      if (cb.checked) state.selected.add(name);
      else state.selected.delete(name);
      render();
    });
    var span = document.createElement("span");
    span.className = "b-name";
    span.textContent = name;
    row.appendChild(cb);
    row.appendChild(span);
    return row;
  }

  function buildBeliefList() {
    var host = document.getElementById("belief-list");
    host.innerHTML = "";
    var filtered = computeFiltered();
    P.beliefTypes.forEach(function (t) {
      if (!state.types.has(t)) return; // section hidden when its type is off
      var beliefs = (P.beliefsByType[t] || []).filter(function (b) {
        return filtered.has(b);
      });
      if (!beliefs.length) return;
      var title = document.createElement("div");
      title.className = "b-section-title";
      title.textContent = SECTION_LABEL[t] || t;
      host.appendChild(title);
      beliefs.forEach(function (b) {
        host.appendChild(beliefRow(b));
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Facet rendering: one facet per displayed era; x = selected beliefs; one
  // offsetgroup per selected yield (grouped). When both benefactors are active,
  // Owner + Follower share an offsetgroup so they stack (Follower lighter).
  // ---------------------------------------------------------------------------
  function cellOf(bucket, y, era, belief) {
    return ((bucket[y] || {})[era] || {})[belief];
  }

  function orderedBeliefs(era, bucket) {
    var rows = [];
    state.selected.forEach(function (b) {
      var total = 0;
      state.yields.forEach(function (y) {
        var cell = cellOf(bucket, y, era, b);
        if (!cell) return;
        if (state.benefactors.has("owner")) total += cell.owner || 0;
        if (state.benefactors.has("follower")) total += cell.follower || 0;
      });
      if (total !== 0) rows.push({ name: b, total: total });
    });
    rows.sort(function (a, b) {
      return b.total - a.total;
    });
    if (state.topN > 0) rows = rows.slice(0, state.topN);
    return rows.map(function (r) {
      return r.name;
    });
  }

  function makeTrace(y, who, color, beliefs, bucket, era) {
    var vals = beliefs.map(function (b) {
      var cell = cellOf(bucket, y, era, b);
      return cell ? cell[who] || 0 : 0;
    });
    var suffix = who === "follower" ? " (Follower)" : " (Owner)";
    return {
      type: "bar",
      name: y + suffix,
      x: beliefs,
      y: vals,
      marker: {
        color: color,
        line: { color: "rgba(0,0,0,0.25)", width: who === "follower" ? 0.5 : 0 },
      },
      offsetgroup: y, // same yield → side-by-side slot; owner+follower stack within it
      cliponaxis: false,
      hovertemplate: "%{x}<br>" + y + suffix + ": %{y:.2f}<extra></extra>",
      showlegend: false,
    };
  }

  function buildFacet(era, container) {
    var bucket = P.data[state.metric] || {};
    var beliefs = orderedBeliefs(era, bucket);

    var wrap = document.createElement("div");
    wrap.className = "facet";
    var title = document.createElement("div");
    title.className = "facet-title";
    title.textContent = era;
    var plot = document.createElement("div");
    plot.className = "plot";
    wrap.appendChild(title);
    wrap.appendChild(plot);
    container.appendChild(wrap);

    var yields = P.yields.filter(function (y) {
      return state.yields.has(y);
    });
    var bothBenefactors =
      state.benefactors.has("owner") && state.benefactors.has("follower");

    var traces = [];
    yields.forEach(function (y) {
      var base = yieldColor(y);
      if (state.benefactors.has("owner")) {
        traces.push(makeTrace(y, "owner", base, beliefs, bucket, era));
      }
      if (state.benefactors.has("follower")) {
        var col = bothBenefactors ? lighten(base, 0.5) : base;
        traces.push(makeTrace(y, "follower", col, beliefs, bucket, era));
      }
    });

    var layout = {
      // "relative" stacks traces that share an offsetgroup (owner+follower of one
      // yield) while placing different offsetgroups (different yields) side by side.
      barmode: "relative",
      margin: { l: 44, r: 10, t: 6, b: 90 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#aab4c4", size: 11 },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: beliefs,
        tickangle: -40,
        automargin: true,
        gridcolor: "rgba(255,255,255,0.04)",
      },
      yaxis: {
        title: { text: "Yield", font: { size: 11 } },
        gridcolor: "rgba(255,255,255,0.07)",
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      showlegend: false,
    };

    Plotly.react(plot, traces, layout, {
      displayModeBar: false,
      responsive: true,
    });
  }

  // Religion report shows one facet per row (one graph per row) regardless of
  // how many display eras are selected.
  function gridColumns() {
    return 1;
  }

  function render() {
    document.getElementById("rel-chart-title").textContent =
      "Religious Belief Yields " +
      (state.metric === "turn" ? "(Per-Turn Average)" : "(Era Totals)");

    var grid = document.getElementById("rel-facet-grid");
    grid.innerHTML = "";

    var eras = P.eraOrder.filter(function (e) {
      return state.displayEras.has(e);
    });

    var hasAny =
      state.selected.size > 0 &&
      eras.length > 0 &&
      state.yields.size > 0 &&
      state.benefactors.size > 0;
    document.getElementById("rel-empty-msg").hidden = hasAny;

    var cols = gridColumns(eras.length || 1);
    grid.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";

    eras.forEach(function (era) {
      buildFacet(era, grid);
    });
  }

  function legendItem(color, label, italic) {
    var item = document.createElement("div");
    item.className = "legend-item";
    if (italic) {
      item.style.fontStyle = "italic";
      item.textContent = label;
      return item;
    }
    var sw = document.createElement("span");
    sw.className = "legend-swatch";
    sw.style.background = color;
    var lab = document.createElement("span");
    lab.textContent = label;
    item.appendChild(sw);
    item.appendChild(lab);
    return item;
  }

  function buildLegend() {
    var host = document.getElementById("rel-legend");
    host.innerHTML = "";
    P.yields.forEach(function (y) {
      if (state.yields.has(y)) host.appendChild(legendItem(yieldColor(y), y, false));
    });
    if (state.benefactors.has("owner") && state.benefactors.has("follower")) {
      host.appendChild(legendItem(null, "Lighter shade = Follower", true));
    }
  }

  // ---------------------------------------------------------------------------
  // Init (builds controls once; the report switcher re-renders on show).
  // ---------------------------------------------------------------------------
  syncSelection();
  buildYieldControls();
  buildMetricControls();
  buildBenefactorControls();
  buildDisplayEraControls();
  buildTopNControls();
  buildFilterTypeControls();
  buildBeliefList();
  buildLegend();
  render();

  window.ReligionReport = { render: render };
})();

/* Report Type switcher — toggles the active report in-page (no reload). */
(function () {
  "use strict";
  var sel = document.getElementById("report-select");
  var app = document.getElementById("app");
  if (!sel || !app) return;

  // report value -> { class on #app, the report module exposing render() }
  var REPORTS = {
    building: { cls: "show-building", mod: "BuildingReport" },
    religion: { cls: "show-religion", mod: "ReligionReport" },
    units: { cls: "show-units", mod: "UnitsReport" },
  };

  function apply() {
    var target = REPORTS[sel.value] || REPORTS.building;
    Object.keys(REPORTS).forEach(function (key) {
      app.classList.toggle(REPORTS[key].cls, REPORTS[key] === target);
    });
    var mod = window[target.mod];
    if (mod) mod.render();
  }

  sel.value = (window.PAYLOAD && window.PAYLOAD.defaultReport) || "building";
  sel.addEventListener("change", apply);
  apply();
})();
