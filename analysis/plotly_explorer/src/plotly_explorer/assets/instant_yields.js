/* Instant Yields report — a sortable, per-column-shaded heatmap table of the
   average instant yield each trigger type grants per era.

   Controls (left sidebar): a mutually-exclusive Yield Type selector and a
   "Trigger Types Displayed" slider. The table shows AvgYieldAmount per
   (trigger type x era); cells are green-shaded relative to their own column;
   hovering a cell shows AvgTriggerAmount and AvgTimesTriggered. Clicking an era
   header cycles the row sort descending -> ascending -> default (default is the
   all-era average, largest on top). Modeled on policies_performance.js (shade()
   + HTML table) and app.js (chip / slider control builders). */
(function () {
  "use strict";

  var P = window.PAYLOAD.instant_yields;

  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";

  // Eras excluded from the default within-era contribution sort (still shown as
  // columns, just not factored into the row score). Information-era data is
  // sparse/noisy enough to skew the shares.
  var SORT_EXCLUDED_ERAS = { Information: true, Atomic: true };

  var state = {
    yield: P.defaultYield || (P.yields[0] || null),
    topN: P.defaultTopN || 15,
    sortEra: null, // era name currently sorted by, or null for the default sort
    sortDir: null, // 'desc' | 'asc' when sortEra is set
  };

  // -------------------------------------------------------------------------
  // Shading — green whose intensity tracks the cell value relative to the max
  // in its own column (sqrt-scaled so mid values stay visible). Copied from
  // policies_performance.js for visual consistency.
  // -------------------------------------------------------------------------
  function shade(value, max) {
    if (!max || value <= 0) return "transparent";
    var t = Math.sqrt(value / max);
    var lo = [16, 40, 28];
    var hi = [46, 170, 90];
    var r = Math.round(lo[0] + (hi[0] - lo[0]) * t);
    var g = Math.round(lo[1] + (hi[1] - lo[1]) * t);
    var b = Math.round(lo[2] + (hi[2] - lo[2]) * t);
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function fmtCell(v) {
    if (!v) return "";
    if (v >= 100) return Math.round(v).toLocaleString();
    if (v >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  function fmtNum(v) {
    return (Math.round(v * 100) / 100).toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }

  // AvgYieldAmount for (type, era), 0 when the trigger never fired in that era.
  function cellY(cells, type, era) {
    var c = cells[type] && cells[type][era];
    return c ? c.y : 0;
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

  function buildYieldControls() {
    var host = document.getElementById("iy-yield-controls");
    host.innerHTML = "";
    P.yields.forEach(function (y) {
      host.appendChild(
        chip(y, y === state.yield, function () {
          if (state.yield === y) return;
          state.yield = y;
          buildYieldControls();
          render();
        })
      );
    });
  }

  function buildTopNControls() {
    var host = document.getElementById("iy-topn-controls");
    host.innerHTML = "";
    var input = document.createElement("input");
    input.type = "range";
    input.min = "1";
    input.max = String(P.maxTriggerTypes || 1);
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

  // Cycle the sort for an era header: desc -> asc -> default (clear).
  function cycleSort(era) {
    if (state.sortEra !== era) {
      state.sortEra = era;
      state.sortDir = "desc";
    } else if (state.sortDir === "desc") {
      state.sortDir = "asc";
    } else {
      state.sortEra = null;
      state.sortDir = null;
    }
    render();
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  function render() {
    var host = document.getElementById("iy-heatmap");
    if (!host) return;
    host.textContent = "";

    var yd = (P.data && P.data[state.yield]) || { types: [], cells: {} };
    var cells = yd.cells || {};
    var types = (yd.types || []).slice();

    // Drop eras with no data for this yield (e.g. Future when nothing of this
    // yield type is ever granted that late). Judge against all trigger types,
    // not just the top-N shown, so the slider doesn't make columns vanish.
    var eras = (P.eraOrder || []).filter(function (era) {
      return types.some(function (type) {
        return cellY(cells, type, era) > 0;
      });
    });

    // If a sorted era got filtered out (e.g. after switching yields), fall back
    // to the default sort so we don't sort by a hidden column.
    if (state.sortEra && eras.indexOf(state.sortEra) === -1) {
      state.sortEra = null;
      state.sortDir = null;
    }

    // Default sort key: mean within-era contribution share. For each era we take
    // a type's value as a fraction of that era's column total (over ALL types, so
    // this sort legitimately decides the top-N), then average those shares across
    // the scored eras — a type absent in an era counts as 0% there. This ranks
    // consistent contributors above single-era magnitude spikes. SORT_EXCLUDED_ERAS
    // (e.g. Information) are left out of the score though still shown as columns.
    var scoreEras = eras.filter(function (era) {
      return !SORT_EXCLUDED_ERAS[era];
    });
    var colTotal = {};
    scoreEras.forEach(function (era) {
      var sum = 0;
      types.forEach(function (type) {
        sum += cellY(cells, type, era);
      });
      colTotal[era] = sum;
    });
    var score = {};
    types.forEach(function (type) {
      var sum = 0;
      scoreEras.forEach(function (era) {
        var tot = colTotal[era];
        if (tot > 0) sum += cellY(cells, type, era) / tot;
      });
      score[type] = scoreEras.length ? sum / scoreEras.length : 0;
    });

    if (state.sortEra) {
      var era = state.sortEra;
      var dir = state.sortDir === "asc" ? 1 : -1;
      types.sort(function (a, b) {
        var d = cellY(cells, a, era) - cellY(cells, b, era);
        if (d !== 0) return dir * d;
        // Stable tiebreak by the contribution score (desc) then name.
        var m = score[b] - score[a];
        return m !== 0 ? m : a.localeCompare(b);
      });
    } else {
      types.sort(function (a, b) {
        var m = score[b] - score[a];
        return m !== 0 ? m : a.localeCompare(b);
      });
    }

    types = types.slice(0, state.topN);

    // Per-column max over the displayed rows, for column-relative shading.
    var colMax = {};
    eras.forEach(function (era) {
      var max = 0;
      types.forEach(function (type) {
        var v = cellY(cells, type, era);
        if (v > max) max = v;
      });
      colMax[era] = max;
    });

    var table = document.createElement("table");

    // Header row.
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    var corner = document.createElement("th");
    corner.textContent = "Trigger Type";
    htr.appendChild(corner);
    eras.forEach(function (era) {
      var th = document.createElement("th");
      th.className = "iy-era-col" + (state.sortEra === era ? " iy-sorted" : "");
      th.appendChild(document.createTextNode(era));
      var arrow = document.createElement("span");
      if (state.sortEra === era) {
        arrow.className = "iy-sort-arrow";
        arrow.textContent = state.sortDir === "asc" ? "▲" : "▼";
      } else {
        // Idle affordance: a dim up/down glyph hinting the header is sortable.
        arrow.className = "iy-sort-arrow iy-sort-idle";
        arrow.textContent = "⇅";
      }
      th.appendChild(arrow);
      th.addEventListener("click", function () {
        cycleSort(era);
      });
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    // Body rows.
    var tbody = document.createElement("tbody");
    types.forEach(function (type) {
      var tr = document.createElement("tr");
      var name = document.createElement("td");
      name.textContent = type;
      name.className = "iy-type-name";
      tr.appendChild(name);
      eras.forEach(function (era) {
        var c = cells[type] && cells[type][era];
        var y = c ? c.y : 0;
        var td = document.createElement("td");
        td.textContent = fmtCell(y);
        td.style.background = shade(y, colMax[era]);
        td.style.color = y > 0 ? TEXT : TEXT_DIM;
        if (c) {
          td.title =
            "Average Amount per Trigger: " +
            fmtNum(c.t) +
            "\nAverage Times Triggered per Era: " +
            fmtNum(c.n);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  buildYieldControls();
  buildTopNControls();
  render();

  window.InstantYieldsReport = { render: render };
})();
