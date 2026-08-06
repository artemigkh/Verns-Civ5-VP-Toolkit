/* Building Yields Grouped (Experimental) report — client-side reactivity.

   An alternate take on the Building Yield report (app.js) with multi-select
   yields: each selected yield becomes a side-by-side offsetgroup whose
   Base/Bonus/Instant segments stack, following the grouped-stacked pattern the
   religion report uses. Hue carries the yield, lightness carries the segment.

   It shares app.js's payload (window.PAYLOAD.building), filters, and building
   list, but owns its own DOM ids (bg-*) and state so the two reports can be
   compared side by side without interfering. app.js remains the single-yield
   original and owns the shared sidebar chrome. */
(function () {
  "use strict";

  var P = window.PAYLOAD.building;

  // Each selected yield gets its own side-by-side slot; Base/Bonus/Instant stack
  // inside it. Hue therefore carries the yield and lightness carries the segment,
  // so the segment colors are derived (segmentColor) rather than fixed.
  var SEGMENTS = [
    { key: "base", label: "Base Yield" },
    { key: "bonus", label: "Bonus Yield" },
    { key: "instant", label: "Instant Yield" },
  ];

  // ---------------------------------------------------------------------------
  // Yield color LUT — kept in sync with the religion report. Yields not listed
  // (e.g. Border Growth Points) get a stable hash-derived fallback.
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

  // Blend a color toward white (lighten) or black (darken); amt in [0,1].
  function blend(color, target, amt) {
    var rgb = toRgb(color);
    if (!rgb) return color;
    return (
      "rgb(" +
      Math.round(rgb[0] + (target - rgb[0]) * amt) +
      "," +
      Math.round(rgb[1] + (target - rgb[1]) * amt) +
      "," +
      Math.round(rgb[2] + (target - rgb[2]) * amt) +
      ")"
    );
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

  function luminance(color) {
    var rgb = toRgb(color);
    if (!rgb) return 0;
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  }

  // Base / Bonus / Instant share the yield's hue and are separated by lightness.
  // Lighten by default; for yields whose color is already near-white (Faith is
  // pure white) darken instead, so all three steps stay distinguishable.
  var SEGMENT_MIX = [0, 0.32, 0.62]; // base, bonus, instant
  function segmentColor(baseColor, i) {
    var amt = SEGMENT_MIX[i];
    if (!amt) return baseColor;
    return blend(baseColor, luminance(baseColor) > 170 ? 0 : 255, amt);
  }

  var uniqueToBase = P.uniqueToBase; // unique replacement -> base it replaces

  var state = {
    yields: new Set(), // multi-select; seeded below
    metric: "turn", // 'turn' | 'total'
    displayEras: new Set(P.defaultDisplayEras),
    filterEras: new Set(["Ancient", "Classical"]), // building-era filter
    types: new Set(["regular", "unique"]), // regular | ww | nw | rel | unique
    topN: 15, // max buildings shown per facet
    selected: new Set(), // checked buildings
  };
  var defaultYield =
    P.yields.indexOf("Production") >= 0 ? "Production" : P.yields[0];
  if (defaultYield) state.yields.add(defaultYield);

  // -------------------------------------------------------------------------
  // Filtering
  //
  // The building filters are positive selectors: a building is eligible only if
  // it matches an enabled era AND an enabled type. An empty section therefore
  // matches nothing, so toggling a filter off strictly removes the buildings it
  // contributed (and toggling one on strictly adds) — which keeps the right-side
  // list and the graph selection in sync with the filter buttons.
  // -------------------------------------------------------------------------
  function matchesType(name) {
    if (state.types.size === 0) return false;
    var info = P.buildingInfo[name] || {};
    if (info.corp) return false;
    var isReplacement = !!uniqueToBase[name]; // a civ-specific unique replacement
    if (state.types.has("ww") && info.ww) return true;
    if (state.types.has("nw") && info.nw) return true;
    if (state.types.has("rel") && info.rel) return true;
    // Unique = only the civ-specific replacements (Tatara, Pitz Court, ...);
    // the standard building each one replaces (Forge, Arena, ...) is Regular.
    if (state.types.has("unique") && isReplacement) return true;
    // Regular = any standard building (including the bases that uniques replace):
    // no wonder/religious/corp modifier and not itself a civ-specific unique.
    if (
      state.types.has("regular") &&
      !info.ww &&
      !info.nw &&
      !info.rel &&
      !info.corp &&
      !isReplacement
    )
      return true;
    return false;
  }

  function matchesEra(name) {
    var info = P.buildingInfo[name];
    // Religious / faith-purchased buildings carry no unlock era, so the era
    // filter doesn't scope them: they're always era-eligible and gated solely
    // by the type filter (the "Religious" chip). Without this, no era could
    // ever match them and they'd be invisible regardless of the type filter.
    if (info && !info.era) return true;
    if (state.filterEras.size === 0) return false;
    return !!(info && info.era && state.filterEras.has(info.era));
  }

  function computeFiltered() {
    var out = new Set();
    // Pool is the union across selected yields: a building is eligible if it has
    // data for at least one of them (and passes the era/type filters).
    state.yields.forEach(function (y) {
      (P.buildingsByYield[y] || []).forEach(function (b) {
        if (matchesEra(b) && matchesType(b)) out.add(b);
      });
    });
    return out;
  }

  // Eligible set from the previous filter state, so a filter change can apply
  // only the delta instead of wiping the user's manual check/uncheck choices.
  var prevEligible = new Set();

  // Sync the checked set to the current filters: drop buildings that are no
  // longer eligible (deselect + remove from the list/graph), auto-check
  // buildings that just became eligible, and leave already-eligible buildings
  // exactly as the user left them.
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

  // -------------------------------------------------------------------------
  // Control builders
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

  function buildYieldControls() {
    var host = document.getElementById("bg-yield-controls");
    host.innerHTML = "";
    P.yields.forEach(function (y) {
      host.appendChild(
        chip(y, state.yields.has(y), function () {
          if (state.yields.has(y)) state.yields.delete(y);
          else state.yields.add(y);
          syncSelection();
          buildYieldControls();
          buildBuildingList();
          render();
        })
      );
    });
  }

  function buildMetricControls() {
    var host = document.getElementById("bg-metric-controls");
    host.innerHTML = "";
    var opts = [
      { key: "turn", label: "Per-Turn Avg" },
      { key: "total", label: "Era Totals" },
    ];
    opts.forEach(function (o) {
      host.appendChild(
        chip(o.label, state.metric === o.key, function () {
          state.metric = o.key;
          buildMetricControls();
          render();
        })
      );
    });
  }

  function buildDisplayEraControls() {
    var host = document.getElementById("bg-display-era-controls");
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

  function buildTopNControls() {
    var host = document.getElementById("bg-topn-controls");
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

  function buildFilterEraControls() {
    var host = document.getElementById("bg-filter-era-controls");
    host.innerHTML = "";
    P.buildingFilterEras.forEach(function (era) {
      host.appendChild(
        chip(era, state.filterEras.has(era), function () {
          if (state.filterEras.has(era)) {
            state.filterEras.delete(era);
          } else {
            state.filterEras.add(era);
            // Selecting a building era auto-enables it as a displayed era.
            state.displayEras.add(era);
            buildDisplayEraControls();
          }
          syncSelection();
          buildFilterEraControls();
          buildBuildingList();
          render();
        })
      );
    });
  }

  function buildFilterTypeControls() {
    var host = document.getElementById("bg-filter-type-controls");
    host.innerHTML = "";
    var opts = [
      { key: "regular", label: "Regular Buildings" },
      { key: "unique", label: "Unique Buildings" },
      { key: "ww", label: "World Wonders" },
      { key: "nw", label: "National Wonders" },
      { key: "rel", label: "Religious" },
    ];
    opts.forEach(function (o) {
      host.appendChild(
        chip(o.label, state.types.has(o.key), function () {
          if (state.types.has(o.key)) state.types.delete(o.key);
          else state.types.add(o.key);
          syncSelection();
          buildFilterTypeControls();
          buildBuildingList();
          render();
        })
      );
    });
  }

  // -------------------------------------------------------------------------
  // Building list (grouped, scrollable checklist)
  // -------------------------------------------------------------------------
  function buildingRow(name, isChild) {
    var row = document.createElement("label");
    row.className = "b-row" + (isChild ? " child" : "");
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

  function buildBuildingList() {
    var host = document.getElementById("bg-building-list");
    host.innerHTML = "";
    var filtered = computeFiltered();

    P.tree.forEach(function (node) {
      var visibleChildren = node.children.filter(function (c) {
        return filtered.has(c);
      });
      if (filtered.has(node.name)) {
        // Base building is eligible: show it with its uniques indented beneath.
        host.appendChild(buildingRow(node.name, false));
        visibleChildren.forEach(function (c) {
          host.appendChild(buildingRow(c, true));
        });
      } else {
        // Base filtered out: drop the header and promote eligible uniques to
        // top-level rows so the removed base no longer lingers in the list.
        visibleChildren.forEach(function (c) {
          host.appendChild(buildingRow(c, false));
        });
      }
    });
  }

  // -------------------------------------------------------------------------
  // Facet rendering
  // -------------------------------------------------------------------------
  function gridColumns(nEras) {
    var w = document.getElementById("main").clientWidth - 20;
    var byWidth = Math.max(1, Math.floor(w / 380));
    // Prefer 2 graphs per row until 5+ display eras are selected; never exceed 3.
    var cap = nEras >= 5 ? 3 : 2;
    // Grouped bars need room: every extra selected yield splits each building's
    // slot again, so give the facets more width instead of more columns.
    if (state.yields.size >= 3) cap = 1;
    else if (state.yields.size === 2) cap = Math.min(cap, 2);
    return Math.min(cap, nEras, byWidth);
  }

  function cellOf(data, y, era, building) {
    return ((data[y] || {})[era] || {})[building];
  }

  // Buildings plotted in one facet, ranked by the height of their whole cluster:
  // all three segments summed over every selected yield. Ordered independently
  // per facet, then capped at the top-N slider.
  function orderedBuildings(era) {
    var data = P.data[state.metric] || {};
    var rows = [];
    state.selected.forEach(function (b) {
      var total = 0;
      state.yields.forEach(function (y) {
        var cell = cellOf(data, y, era, b);
        if (!cell) return;
        total += (cell.base || 0) + (cell.bonus || 0) + (cell.instant || 0);
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

  function fmt(v, decimals) {
    if (!v) return "";
    return v.toFixed(decimals);
  }

  // Compact sample-size formatting for the tooltip "n=…" line: at most 3
  // significant digits, SI-suffixed (5.21 K, 6.32 M) once past 999.
  function fmtCount(n) {
    n = n || 0;
    if (n < 1000) return String(Math.round(n));
    var units = [
      { d: 1e9, s: "B" },
      { d: 1e6, s: "M" },
      { d: 1e3, s: "K" },
    ];
    for (var i = 0; i < units.length; i++) {
      if (n >= units[i].d) {
        var v = n / units[i].d;
        var str = v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
        return str + " " + units[i].s;
      }
    }
    return String(Math.round(n));
  }

  // Legible ink on a bar-colored background (inside labels and hover labels):
  // dark on light bars, light on dark ones. The yield palette spans pure white
  // through deep brown/blue, so this has to be picked per trace.
  function insideTextColor(color) {
    return luminance(color) > 150 ? "#0e1117" : "#f2f5fa";
  }

  // -------------------------------------------------------------------------
  // Dynamic bar-label precision: estimate how many characters fit across one
  // bar (labels are horizontal, 10px font) and shrink from 2 decimals down to
  // 0; when fewer than 3 characters fit (or the integer part alone doesn't),
  // omit the labels entirely instead of letting Plotly clip them.
  // -------------------------------------------------------------------------
  var LABEL_CHAR_PX = 6; // approx digit width at the 10px annotation font
  function labelDecimals(values, barPx) {
    var maxAbs = 0;
    values.forEach(function (v) {
      maxAbs = Math.max(maxAbs, Math.abs(v));
    });
    var intDigits = maxAbs >= 1 ? Math.floor(Math.log10(maxAbs)) + 1 : 1;
    var fits = Math.floor(barPx / LABEL_CHAR_PX);
    if (fits < 3 || fits < intDigits) return -1; // omit labels entirely
    if (fits >= intDigits + 3) return 2; // room for "12.34"
    if (fits >= intDigits + 2) return 1; // room for "12.3"
    return 0;
  }

  // -------------------------------------------------------------------------
  // x-axis label coloring: unique buildings blue, national wonders lighter
  // orange, world wonders a deeper orange-red. Everything else keeps the
  // default dimmed tick color.
  // -------------------------------------------------------------------------
  var LABEL_DEFAULT = "#aab4c4";
  function labelColor(name) {
    var info = P.buildingInfo[name] || {};
    // Unique takes precedence: a civ-specific unique that also carries a wonder
    // flag is colored blue, not orange.
    if (uniqueToBase[name]) return "#5aa9e6"; // unique building — blue
    if (info.ww) return "#e35d3b"; // world wonder — deep orange/red
    if (info.nw) return "#f0a24e"; // national wonder — lighter orange
    return LABEL_DEFAULT;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function coloredTicks(names) {
    return names.map(function (name) {
      return (
        '<span style="color:' + labelColor(name) + '">' + esc(name) + "</span>"
      );
    });
  }

  // Which category label-colors actually occur in the dataset (respecting the
  // unique-precedence rule), so the legend key can omit categories no building
  // ever falls into. Computed once — the building set is fixed for the payload.
  var presentLabelColors = (function () {
    var set = {};
    Object.keys(P.buildingInfo).forEach(function (name) {
      set[labelColor(name)] = true;
    });
    return set;
  })();

  function makeTrace(y, seg, color, names, era, data) {
    var vals = names.map(function (b) {
      var cell = cellOf(data, y, era, b);
      return cell ? cell[seg.key] || 0 : 0;
    });
    var label = y + " " + seg.label;
    return {
      type: "bar",
      name: label,
      x: names,
      y: vals,
      // [plain building name, sample size]. The name is fed through customdata
      // (not %{x}) so the tooltip renders it in the legible hoverlabel color
      // rather than the blue/orange category color baked into the axis ticktext.
      customdata: names.map(function (b) {
        var cell = cellOf(data, y, era, b);
        return [b, fmtCount(cell ? cell.n || 0 : 0)];
      }),
      marker: {
        color: color,
        // Hairline between the stacked segments so their boundaries read even
        // when the shade steps are subtle. The base segment sits on the axis.
        line: {
          color: "rgba(0,0,0,0.3)",
          width: seg.key === "base" ? 0 : 0.5,
        },
      },
      offsetgroup: y, // same yield → side-by-side slot; segments stack within it
      cliponaxis: false,
      // Tooltip text stays legible (black/white on the bar-colored label)
      // instead of inheriting the category coloring used on the axis labels.
      hoverlabel: { font: { color: insideTextColor(color) } },
      hovertemplate:
        "%{customdata[0]}<br>" + label + ": %{y:.2f}<br>n=%{customdata[1]}<extra></extra>",
      showlegend: false,
    };
  }

  function buildFacet(era, container) {
    var data = P.data[state.metric] || {};
    var names = orderedBuildings(era);

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

    // Drive trace order off the payload's canonical yield order rather than the
    // Set's insertion order, so the side-by-side slots don't shuffle as chips
    // are toggled off and back on.
    var yields = P.yields.filter(function (y) {
      return state.yields.has(y);
    });

    var traces = [];
    yields.forEach(function (y) {
      var base = yieldColor(y);
      // Pushed base → bonus → instant: traces sharing an offsetgroup stack in
      // trace order, so this puts the base yield at the bottom.
      SEGMENTS.forEach(function (seg, i) {
        traces.push(makeTrace(y, seg, segmentColor(base, i), names, era, data));
      });
    });

    // Dynamic value labels: each building group is split into one side-by-side
    // slot per selected yield, so a bar is that much narrower than the group.
    var numYields = yields.length || 1;
    var avail = Math.max(40, (plot.clientWidth || 380) - 54);
    var barPx =
      ((names.length ? avail / names.length : avail) * 0.8) / numYields;
    var allVals = [];
    traces.forEach(function (t) {
      t.y.forEach(function (v) {
        if (v) allVals.push(v);
      });
    });
    var decimals = labelDecimals(allVals, barPx);
    if (decimals >= 0) {
      traces.forEach(function (t) {
        t.text = t.y.map(function (v) {
          return fmt(v, decimals);
        });
        t.texttemplate = "%{text}";
        // Place inside when it fits, otherwise on top of the bar; never rotate.
        t.textposition = "auto";
        t.textangle = 0;
        t.insidetextanchor = "middle";
        t.constraintext = "none";
        t.insidetextfont = { size: 10, color: insideTextColor(t.marker.color) };
        t.outsidetextfont = { size: 10, color: "#d7dde7" };
      });
    }

    var x = names;

    var layout = {
      // "relative" stacks traces that share an offsetgroup (the three segments of
      // one yield) while placing different offsetgroups (yields) side by side.
      barmode: "relative",
      margin: { l: 44, r: 10, t: 6, b: 90 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#aab4c4", size: 11 },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: x,
        tickmode: "array",
        tickvals: x.map(function (_, i) { return i; }),
        ticktext: coloredTicks(x),
        tickangle: -40,
        automargin: true,
        // Draw the vertical grid lines on the category boundaries (between
        // building groups) rather than through each label's center, so the bars
        // of one building read as a single cluster even when a middle yield is 0.
        tickson: "boundaries",
        showgrid: true,
        gridcolor: "rgba(255,255,255,0.14)",
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

  // Yields currently selected, in the payload's canonical order.
  function activeYields() {
    return P.yields.filter(function (y) {
      return state.yields.has(y);
    });
  }

  function render() {
    // A single yield still names itself in the title; past that the heading goes
    // generic and the legend carries which yields are on screen.
    var sel = activeYields();
    document.getElementById("bg-chart-title").textContent =
      (sel.length === 1 ? sel[0] + " Yield " : "Building Yields ") +
      (state.metric === "turn" ? "(Per-Turn Average)" : "(Era Totals)");
    document.getElementById("bg-chart-subtitle").textContent =
      state.metric === "turn"
        ? "Average per-turn yields produced by an individual building copy within each era"
        : "Average yields produced by an individual building copy across each era";

    var grid = document.getElementById("bg-facet-grid");
    grid.innerHTML = "";

    var eras = P.eraOrder.filter(function (e) {
      return state.displayEras.has(e);
    });

    var hasAny =
      state.selected.size > 0 && eras.length > 0 && state.yields.size > 0;
    document.getElementById("bg-empty-msg").hidden = hasAny;

    var cols = gridColumns(eras.length || 1);
    grid.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";

    eras.forEach(function (era) {
      buildFacet(era, grid);
    });

    // Rebuild the legend so its category key reflects the current type-filter
    // selection (categories are hidden when their filter is toggled off).
    buildLegend();
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
    var host = document.getElementById("bg-legend");
    host.innerHTML = "";
    // Hue carries the yield, lightness carries the segment. With one yield the
    // hue is unambiguous, so only the segment ramp is shown; past that the
    // yields get their own swatches first.
    var sel = activeYields();
    if (sel.length > 1) {
      sel.forEach(function (y) {
        host.appendChild(legendItem(yieldColor(y), y, false));
      });
    }
    if (sel.length) {
      // Ramp demonstrated on the first selected yield, so the shades in the key
      // are literally shades that appear on screen.
      var base = yieldColor(sel[0]);
      SEGMENTS.forEach(function (seg, i) {
        host.appendChild(legendItem(segmentColor(base, i), seg.label, false));
      });
      if (sel.length > 1) {
        host.appendChild(
          legendItem(null, "Shades = stack order within each yield", true)
        );
      }
    }
    // Key for the x-axis label colors (building categories). Each entry shows
    // only when the dataset actually contains a building of that color AND the
    // matching type filter is currently enabled.
    [
      { type: "unique", color: "#5aa9e6", label: "Unique Building" },
      { type: "nw", color: "#f0a24e", label: "National Wonder" },
      { type: "ww", color: "#e35d3b", label: "World Wonder" },
    ].forEach(function (c) {
      if (!presentLabelColors[c.color] || !state.types.has(c.type)) return;
      var item = document.createElement("div");
      item.className = "legend-item";
      var lab = document.createElement("span");
      lab.style.color = c.color;
      lab.style.fontWeight = "600";
      lab.textContent = c.label;
      item.appendChild(lab);
      host.appendChild(item);
    });
  }

  // -------------------------------------------------------------------------
  // Init (builds controls once; the report switcher re-renders on show).
  //
  // The sidebar chrome and the window-resize reflow are owned by app.js and
  // shared across every report, so this module only registers itself.
  // -------------------------------------------------------------------------
  syncSelection();
  buildYieldControls();
  buildMetricControls();
  buildDisplayEraControls();
  buildTopNControls();
  buildFilterEraControls();
  buildFilterTypeControls();
  buildBuildingList();
  render();

  // Expose this report's render so the shared chrome + report switcher can reflow it.
  window.BuildingGroupedReport = { render: render };
})();

