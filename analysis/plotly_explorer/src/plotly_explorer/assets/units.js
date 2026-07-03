/* Unit Composition report — client-side reactivity (no backend).

   For the civ picked in the right sidebar, each era facet shows the average
   number of each unit type present on the map in an average turn within that
   era. Bars are single-colored by a domain/ranged/mounted/non-combat category.
   There is no per-unit checklist: every unit passing the left-side filters (and
   with data for the selected civ) is plotted, sorted descending, capped by the
   "Units Per Graph" slider. */
(function () {
  "use strict";

  var P = window.PAYLOAD.units;

  // category key -> bar color, from the server-provided legend.
  var CAT_COLOR = {};
  P.legend.forEach(function (e) {
    CAT_COLOR[e.key] = e.color;
  });

  // Civs that actually have data in this dataset (all 43 are listed, but many
  // may be empty). Used only to pick a sensible default selection.
  var civsWithData = P.civs.filter(function (c) {
    return !!P.data[c];
  });

  var state = {
    civ: civsWithData.length ? civsWithData[0] : P.civs[0],
    displayEras: new Set(P.defaultDisplayEras),
    filterEras: new Set(P.unitFilterEras), // unit unlock eras (all on)
    unitTypes: new Set(P.combatClasses), // combat classes (all on)
    nonCombat: false, // civilian/support units off by default
    domains: new Set(P.domains), // Land / Sea / Air (all on)
    ranged: new Set(["ranged", "melee"]),
    mounted: new Set(["mounted", "notmounted"]),
    topN: 15,
  };

  // -------------------------------------------------------------------------
  // Filtering: a unit is eligible only if it passes every category (OR within a
  // category, AND across categories). Civilian units are gated solely by the
  // Non-Combat toggle (they are not listed among the combat-class chips).
  // -------------------------------------------------------------------------
  function matchesUnit(name) {
    var info = P.unitInfo[name];
    if (!info) return false;
    if (info.non_combat) {
      if (!state.nonCombat) return false;
    } else if (!state.unitTypes.has(info.combat_class)) {
      return false;
    }
    if (!info.era || !state.filterEras.has(info.era)) return false;
    if (!state.domains.has(info.domain)) return false;
    if (!state.ranged.has(info.is_ranged ? "ranged" : "melee")) return false;
    if (!state.mounted.has(info.is_mounted ? "mounted" : "notmounted"))
      return false;
    return true;
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

  // Toggle a value in a Set-backed filter, then rebuild that control + render.
  function toggler(set, key, rebuild) {
    return function () {
      if (set.has(key)) set.delete(key);
      else set.add(key);
      rebuild();
      render();
    };
  }

  function buildDisplayEraControls() {
    var host = document.getElementById("unit-display-era-controls");
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
    var host = document.getElementById("unit-topn-controls");
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

  function buildUnitTypeControls() {
    var host = document.getElementById("unit-type-controls");
    host.innerHTML = "";
    P.combatClasses.forEach(function (cc) {
      host.appendChild(
        chip(cc, state.unitTypes.has(cc), toggler(state.unitTypes, cc, buildUnitTypeControls))
      );
    });
    // The whole civilian/support group collapses into one chip (default off).
    host.appendChild(
      chip("Non-Combat", state.nonCombat, function () {
        state.nonCombat = !state.nonCombat;
        buildUnitTypeControls();
        render();
      })
    );
  }

  function buildChipGroup(hostId, opts, set, rebuild) {
    var host = document.getElementById(hostId);
    host.innerHTML = "";
    opts.forEach(function (o) {
      host.appendChild(
        chip(o.label, set.has(o.key), toggler(set, o.key, rebuild))
      );
    });
  }

  function buildDomainControls() {
    buildChipGroup(
      "unit-domain-controls",
      P.domains.map(function (d) {
        return { key: d, label: d };
      }),
      state.domains,
      buildDomainControls
    );
  }

  function buildRangedControls() {
    buildChipGroup(
      "unit-ranged-controls",
      [
        { key: "melee", label: "Melee" },
        { key: "ranged", label: "Ranged" },
      ],
      state.ranged,
      buildRangedControls
    );
  }

  function buildMountedControls() {
    buildChipGroup(
      "unit-mounted-controls",
      [
        { key: "notmounted", label: "Not Mounted" },
        { key: "mounted", label: "Mounted" },
      ],
      state.mounted,
      buildMountedControls
    );
  }

  function buildFilterEraControls() {
    buildChipGroup(
      "unit-filter-era-controls",
      P.unitFilterEras.map(function (e) {
        return { key: e, label: e };
      }),
      state.filterEras,
      buildFilterEraControls
    );
  }

  // -------------------------------------------------------------------------
  // Right sidebar: mutually-exclusive civ radio list (drives the data).
  // -------------------------------------------------------------------------
  function buildCivList() {
    var host = document.getElementById("civ-list");
    host.innerHTML = "";
    P.civs.forEach(function (civ) {
      var row = document.createElement("label");
      row.className = "b-row";
      var rb = document.createElement("input");
      rb.type = "radio";
      rb.name = "unit-civ";
      rb.checked = civ === state.civ;
      rb.addEventListener("change", function () {
        if (rb.checked) {
          state.civ = civ;
          render();
        }
      });
      var span = document.createElement("span");
      span.className = "b-name";
      span.textContent = civ;
      if (!P.data[civ]) span.classList.add("no-data");
      row.appendChild(rb);
      row.appendChild(span);
      host.appendChild(row);
    });
  }

  // -------------------------------------------------------------------------
  // Facet rendering
  // -------------------------------------------------------------------------
  function gridColumns(nEras) {
    var w = document.getElementById("main").clientWidth - 20;
    var byWidth = Math.max(1, Math.floor(w / 380));
    var cap = nEras >= 5 ? 3 : 2;
    return Math.min(cap, nEras, byWidth);
  }

  function facetData(era) {
    var bucket = (P.data[state.civ] || {})[era] || {};
    var rows = [];
    Object.keys(bucket).forEach(function (u) {
      if (!matchesUnit(u)) return;
      var v = bucket[u];
      if (!v) return;
      var info = P.unitInfo[u] || {};
      rows.push({ name: u, value: v, color: CAT_COLOR[info.category] || "#888888" });
    });
    rows.sort(function (a, b) {
      return b.value - a.value;
    });
    if (state.topN > 0) rows = rows.slice(0, state.topN);
    return rows;
  }

  function fmt(v, decimals) {
    if (!v) return "";
    return v.toFixed(decimals);
  }

  // Dynamic bar-label precision (same scheme as the building report): shrink
  // from 2 decimals to 0 as bars narrow; omit labels once fewer than 3
  // characters (or the integer part) would fit.
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
    var y = rows.map(function (r) {
      return r.value;
    });

    // Estimated width of one bar: plot width minus the l/r margins, split
    // across the bars, less Plotly's default category gap (~20%).
    var avail = Math.max(40, (plot.clientWidth || 380) - 54);
    var barPx = (rows.length ? avail / rows.length : avail) * 0.8;
    var decimals = labelDecimals(y, barPx);
    var showText = decimals >= 0;

    var trace = {
      type: "bar",
      x: x,
      y: y,
      marker: { color: rows.map(function (r) { return r.color; }) },
      text: showText
        ? y.map(function (v) {
            return fmt(v, decimals);
          })
        : undefined,
      texttemplate: showText ? "%{text}" : undefined,
      textposition: "auto",
      textangle: 0,
      insidetextanchor: "middle",
      constraintext: "none",
      insidetextfont: { size: 10, color: "#0e1117" },
      outsidetextfont: { size: 10, color: "#d7dde7" },
      cliponaxis: false,
      hovertemplate: "%{x}<br>Avg count: %{y:.2f}<extra></extra>",
      showlegend: false,
    };

    var layout = {
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
        title: { text: "Avg units", font: { size: 11 } },
        gridcolor: "rgba(255,255,255,0.07)",
        zerolinecolor: "rgba(255,255,255,0.12)",
        rangemode: "tozero",
      },
      showlegend: false,
    };

    Plotly.react(plot, [trace], layout, {
      displayModeBar: false,
      responsive: true,
    });
    return rows;
  }

  function render() {
    document.getElementById("unit-chart-title").textContent =
      "Average Unit Composition — " + state.civ;

    var grid = document.getElementById("unit-facet-grid");
    grid.innerHTML = "";

    var eras = P.eraOrder.filter(function (e) {
      return state.displayEras.has(e);
    });

    var cols = gridColumns(eras.length || 1);
    grid.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";

    var any = false;
    eras.forEach(function (era) {
      if (buildFacet(era, grid).length) any = true;
    });

    document.getElementById("unit-empty-msg").hidden = any && eras.length > 0;
  }

  function buildLegend() {
    var host = document.getElementById("unit-legend");
    host.innerHTML = "";
    P.legend.forEach(function (cat) {
      var item = document.createElement("div");
      item.className = "legend-item";
      var sw = document.createElement("span");
      sw.className = "legend-swatch";
      sw.style.background = cat.color;
      // A border keeps the white "Air" swatch visible on the dark background.
      sw.style.border = "1px solid rgba(255,255,255,0.35)";
      var label = document.createElement("span");
      label.textContent = cat.label;
      item.appendChild(sw);
      item.appendChild(label);
      host.appendChild(item);
    });
  }

  // -------------------------------------------------------------------------
  // Init (the shared chrome/report switcher re-renders on show).
  // -------------------------------------------------------------------------
  buildDisplayEraControls();
  buildTopNControls();
  buildUnitTypeControls();
  buildDomainControls();
  buildRangedControls();
  buildMountedControls();
  buildFilterEraControls();
  buildCivList();
  buildLegend();
  render();

  window.UnitsReport = { render: render };
})();
