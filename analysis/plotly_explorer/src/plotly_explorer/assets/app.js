/* Building Yield report — client-side reactivity (no backend). */
(function () {
  "use strict";

  var P = window.PAYLOAD.building;

  var COLORS = { base: "#4f9da6", bonus: "#7c83ff", instant: "#e0a458" };
  var SEGMENTS = [
    { key: "base", label: "Base Yield", color: COLORS.base },
    { key: "bonus", label: "Bonus Yield", color: COLORS.bonus },
    { key: "instant", label: "Instant Yield", color: COLORS.instant },
  ];

  var uniqueToBase = P.uniqueToBase; // unique replacement -> base it replaces

  var state = {
    yield: P.yields.indexOf("Production") >= 0 ? "Production" : P.yields[0],
    metric: "turn", // 'turn' | 'total'
    displayEras: new Set(P.defaultDisplayEras),
    filterEras: new Set(["Ancient", "Classical"]), // building-era filter
    types: new Set(["regular", "unique"]), // regular | ww | nw | rel | unique
    topN: 15, // max buildings shown per facet
    selected: new Set(), // checked buildings
  };

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
    var isReplacement = !!uniqueToBase[name]; // a civ-specific unique replacement
    if (state.types.has("ww") && info.ww) return true;
    if (state.types.has("nw") && info.nw) return true;
    if (state.types.has("rel") && info.rel) return true;
    // Unique = only the civ-specific replacements (Tatara, Pitz Court, ...);
    // the standard building each one replaces (Forge, Arena, ...) is Regular.
    if (state.types.has("unique") && isReplacement) return true;
    // Regular = any standard building (including the bases that uniques replace):
    // no wonder/religious modifier and not itself a civ-specific unique.
    if (
      state.types.has("regular") &&
      !info.ww &&
      !info.nw &&
      !info.rel &&
      !isReplacement
    )
      return true;
    return false;
  }

  function matchesEra(name) {
    if (state.filterEras.size === 0) return false;
    var info = P.buildingInfo[name];
    return !!(info && info.era && state.filterEras.has(info.era));
  }

  function computeFiltered() {
    var pool = P.buildingsByYield[state.yield] || [];
    var out = new Set();
    pool.forEach(function (b) {
      if (matchesEra(b) && matchesType(b)) out.add(b);
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
    var host = document.getElementById("yield-controls");
    host.innerHTML = "";
    P.yields.forEach(function (y) {
      host.appendChild(
        chip(y, y === state.yield, function () {
          if (state.yield === y) return;
          state.yield = y;
          syncSelection();
          buildYieldControls();
          buildBuildingList();
          render();
        })
      );
    });
  }

  function buildMetricControls() {
    var host = document.getElementById("metric-controls");
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
    var host = document.getElementById("display-era-controls");
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
    var host = document.getElementById("topn-controls");
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
    var host = document.getElementById("filter-era-controls");
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
    var host = document.getElementById("filter-type-controls");
    host.innerHTML = "";
    var opts = [
      { key: "regular", label: "Regular Buildings" },
      { key: "ww", label: "World Wonders" },
      { key: "nw", label: "National Wonders" },
      { key: "rel", label: "Religious" },
      { key: "unique", label: "Unique Buildings" },
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
    var host = document.getElementById("building-list");
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
    return Math.min(cap, nEras, byWidth);
  }

  function facetData(era) {
    var bucket = (P.data[state.metric][state.yield] || {})[era] || {};
    var rows = [];
    state.selected.forEach(function (b) {
      var v = bucket[b];
      if (!v) return;
      var total = (v.base || 0) + (v.bonus || 0) + (v.instant || 0);
      if (total === 0) return;
      rows.push({ name: b, base: v.base || 0, bonus: v.bonus || 0, instant: v.instant || 0, total: total });
    });
    rows.sort(function (a, b) {
      return b.total - a.total;
    });
    if (state.topN > 0) rows = rows.slice(0, state.topN);
    return rows;
  }

  function fmt(v) {
    if (!v) return "";
    return v.toFixed(2);
  }

  function buildFacet(era, container) {
    var rows = facetData(era);
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

    var x = rows.map(function (r) {
      return r.name;
    });

    var traces = SEGMENTS.map(function (seg) {
      var vals = rows.map(function (r) {
        return r[seg.key];
      });
      return {
        type: "bar",
        name: seg.label,
        x: x,
        y: vals,
        marker: { color: seg.color },
        text: vals.map(fmt),
        texttemplate: "%{text}",
        // Place inside when it fits, otherwise on top of the bar; never rotate.
        textposition: "auto",
        textangle: 0,
        insidetextanchor: "middle",
        constraintext: "none",
        insidetextfont: { size: 10, color: "#0e1117" },
        outsidetextfont: { size: 10, color: "#d7dde7" },
        cliponaxis: false,
        hovertemplate: "%{x}<br>" + seg.label + ": %{y:.2f}<extra></extra>",
        showlegend: false,
      };
    });

    var layout = {
      barmode: "stack",
      margin: { l: 44, r: 10, t: 6, b: 90 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#aab4c4", size: 11 },
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: x,
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

  function render() {
    document.getElementById("chart-title").textContent =
      state.yield +
      " Yield " +
      (state.metric === "turn" ? "(Per-Turn Average)" : "(Era Totals)");

    var grid = document.getElementById("facet-grid");
    grid.innerHTML = "";

    var eras = P.eraOrder.filter(function (e) {
      return state.displayEras.has(e);
    });

    var hasAny = state.selected.size > 0 && eras.length > 0;
    document.getElementById("empty-msg").hidden = hasAny;

    var cols = gridColumns(eras.length || 1);
    grid.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";

    eras.forEach(function (era) {
      buildFacet(era, grid);
    });
  }

  function buildLegend() {
    var host = document.getElementById("legend");
    host.innerHTML = "";
    SEGMENTS.forEach(function (seg) {
      var item = document.createElement("div");
      item.className = "legend-item";
      var sw = document.createElement("span");
      sw.className = "legend-swatch";
      sw.style.background = seg.color;
      var label = document.createElement("span");
      label.textContent = seg.label;
      item.appendChild(sw);
      item.appendChild(label);
      host.appendChild(item);
    });
  }

  // -------------------------------------------------------------------------
  // Sidebar: collapse + drag-to-resize
  // -------------------------------------------------------------------------
  var SIDEBAR_MIN = 170;
  var SIDEBAR_MAX = 560;

  // The sidebars (collapse + drag-to-resize) are shared chrome owned by this
  // module, but a width change must reflow whichever report is currently shown.
  function renderActive() {
    var app = document.getElementById("app");
    if (app && app.classList.contains("show-religion") && window.ReligionReport) {
      window.ReligionReport.render();
    } else {
      render();
    }
  }

  // Wire one collapse/expand pair + drag-to-resize handle.
  function makeSidebar(opts) {
    var app = document.getElementById("app");
    var sidebar = document.getElementById(opts.sidebarId);
    var resizer = document.getElementById(opts.resizerId);

    document
      .getElementById(opts.collapseBtnId)
      .addEventListener("click", function () {
        app.classList.add(opts.collapsedClass);
        renderActive();
      });
    document
      .getElementById(opts.expandBtnId)
      .addEventListener("click", function () {
        app.classList.remove(opts.collapsedClass);
        renderActive();
      });

    var dragging = false;
    var rafPending = false;

    function widthFromEvent(e) {
      // Left sidebar hugs the left edge (width == clientX); the right one hugs
      // the right edge (width == viewport width - clientX).
      var raw = opts.side === "left" ? e.clientX : window.innerWidth - e.clientX;
      return Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, raw));
    }

    function onMove(e) {
      if (!dragging) return;
      sidebar.style.width = widthFromEvent(e) + "px";
      if (!rafPending) {
        rafPending = true;
        requestAnimationFrame(function () {
          rafPending = false;
          renderActive();
        });
      }
    }

    function stop() {
      if (!dragging) return;
      dragging = false;
      resizer.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      renderActive();
    }

    resizer.addEventListener("mousedown", function (e) {
      dragging = true;
      resizer.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", stop);
  }

  function setupSidebar() {
    makeSidebar({
      side: "left",
      sidebarId: "sidebar",
      resizerId: "resizer",
      collapseBtnId: "collapse-btn",
      expandBtnId: "expand-btn",
      collapsedClass: "collapsed",
    });
    makeSidebar({
      side: "right",
      sidebarId: "sidebar-right",
      resizerId: "resizer-right",
      collapseBtnId: "collapse-btn-right",
      expandBtnId: "expand-btn-right",
      collapsedClass: "collapsed-right",
    });
  }

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderActive, 150);
  });

  setupSidebar();
  syncSelection();
  buildYieldControls();
  buildMetricControls();
  buildDisplayEraControls();
  buildTopNControls();
  buildFilterEraControls();
  buildFilterTypeControls();
  buildBuildingList();
  buildLegend();
  render();

  // Expose this report's render so the shared chrome + report switcher can reflow it.
  window.BuildingReport = { render: render };
})();
