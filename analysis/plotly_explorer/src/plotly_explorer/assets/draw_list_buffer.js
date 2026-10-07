/* Interface Draw List Buffer (dev) report — what fills the EXE's 1 MB per-frame
   interface draw list, and how much of it is left for unit flags.

   Like Process Memory, this report has no pipeline behind it: PAYLOAD.draw_list_buffer
   is assets/draw_list_buffer.json passed straight through (see its _comment for where
   the measurements come from).

   No controls and no URL state: one donut per measured scene, faceted side by side,
   then the per-action bars, the frame-size bars with their units-that-fit heatmap
   and the cost table.
   Modeled on civs.js (Plotly donut) and wonders.js (explicitly sized plots). */
(function () {
  "use strict";

  var P = window.PAYLOAD.draw_list_buffer;

  var BG = "#161c27"; // the card colour: slice separators read as gaps
  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";
  var GRID = "rgba(255,255,255,0.07)";
  var FREE = "#3a4352"; // empty space: gray, deliberately not a series colour
  var OVER = "#e5484d";

  // responsive:true is intentionally omitted, as in wonders.js: every chart is
  // sized explicitly from its host, and re-sized by render() when the pane changes.
  var PLOT_CONFIG = { displayModeBar: false };

  // Draw `traces` into host `id` at the host's own width. A hidden host has no
  // width: skip it, the router calls render() again when the report is shown.
  function draw(id, traces, layout) {
    var host = document.getElementById(id);
    if (!host.clientWidth) return;
    layout.width = host.clientWidth;
    layout.autosize = false;
    Plotly.react(host, traces, layout, PLOT_CONFIG);
  }

  function fmtB(n) {
    return Math.round(n).toLocaleString() + " B";
  }

  function fmtKB(n) {
    return Math.round(n / 1024).toLocaleString() + " KB";
  }

  function pct(n) {
    return ((100 * n) / P.capacity).toFixed(1) + "%";
  }

  // The scene's users in the payload's fixed order, so a user keeps its place
  // (and colour) on the ring in every facet.
  function sceneUsers(sc) {
    return P.users.filter(function (u) {
      return sc.users[u.key];
    });
  }

  // -------------------------------------------------------------------------
  // Facet scaffolding — one titled cell per scene. Static: built once.
  // -------------------------------------------------------------------------
  function buildDonutGrid() {
    var host = document.getElementById("dlb-donut-grid");
    host.innerHTML = "";
    P.scenes.forEach(function (sc) {
      var cell = document.createElement("div");
      cell.className = "dlb-facet";
      var h = document.createElement("h3");
      h.className = "dlb-facet-title";
      h.textContent = sc.label;
      var note = document.createElement("p");
      note.className = "dlb-facet-note";
      note.textContent = sc.note;
      var plot = document.createElement("div");
      plot.id = "dlb-donut-" + sc.key;
      plot.className = "dlb-plot-donut";
      cell.appendChild(h);
      cell.appendChild(note);
      cell.appendChild(plot);
      host.appendChild(cell);
    });
  }

  // -------------------------------------------------------------------------
  // Chart 1 — who uses the buffer, with the unused part of the 1 MB in gray.
  // One donut per scene.
  // -------------------------------------------------------------------------
  function renderDonut(sc) {
    var users = sceneUsers(sc);
    var labels = users.map(function (u) {
      return u.label;
    });
    var values = users.map(function (u) {
      return sc.users[u.key].bytes;
    });
    var colors = users.map(function (u) {
      return u.color;
    });
    var free = P.capacity - sc.used;
    if (free > 0) {
      labels.push("Empty");
      values.push(free);
      colors.push(FREE);
    }
    var trace = {
      type: "pie",
      hole: 0.62,
      labels: labels,
      values: values,
      marker: { colors: colors, line: { color: BG, width: 2 } },
      sort: false,
      direction: "clockwise",
      // A nearly empty frame is all small slices: started at 12 o'clock their
      // labels pile up over the title, so start them on the right-hand side.
      rotation: sc.used / P.capacity < 0.25 ? 55 : 0,
      customdata: values.map(pct),
      texttemplate: "<b>%{label}</b><br>%{customdata}",
      // Slices under 2% of the buffer keep their hover but lose the label: their
      // labels stack on top of each other at the foot of the ring.
      textposition: values.map(function (v) {
        return v / P.capacity < 0.02 ? "none" : "outside";
      }),
      outsidetextfont: { color: TEXT, size: 12 },
      hovertemplate: "%{label}<br>%{value:,} B (%{customdata} of the buffer)<extra></extra>",
    };
    var over = sc.used > P.capacity;
    var layout = {
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      // Fixed margins, as in civs.js: automargin on outside labels thrashes.
      margin: { l: 120, r: 150, t: 30, b: 40 },
      height: 400,
      font: { color: TEXT },
      annotations: [
        {
          text:
            "<b>" + pct(sc.used) + "</b><br>" +
            '<span style="font-size:12px;color:' + (over ? OVER : TEXT_DIM) + '">' +
            (over ? "over capacity" : fmtKB(sc.used) + " of 1,024 KB") + "</span>",
          x: 0.5,
          y: 0.5,
          showarrow: false,
          font: { color: over ? OVER : TEXT, size: 24 },
        },
      ],
    };
    draw("dlb-donut-" + sc.key, [trace], layout);
  }

  // -------------------------------------------------------------------------
  // Chart 2 — what one player action (a window, a zoom, an icon toggle) adds
  // -------------------------------------------------------------------------
  function renderActions() {
    var rows = P.actions.slice().reverse(); // largest first reads top-down
    var traces = P.actionGroups.map(function (g) {
      var mine = rows.filter(function (r) {
        return r.group === g.key;
      });
      return {
        type: "bar",
        orientation: "h",
        name: g.label,
        y: mine.map(function (r) {
          return r.label;
        }),
        x: mine.map(function (r) {
          return r.added;
        }),
        marker: { color: g.color },
        text: mine.map(function (r) {
          return pct(r.added);
        }),
        textposition: "outside",
        textfont: { color: TEXT_DIM, size: 12 },
        cliponaxis: false,
        hovertemplate: "%{y}<br>adds %{x:,} B (%{text} of the buffer)<extra></extra>",
      };
    });
    var layout = {
      barmode: "overlay",
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: FRAME_LABEL_PX, r: 70, t: 40, b: 50 },
      height: 100 + 30 * rows.length,
      font: { color: TEXT },
      xaxis: {
        title: { text: "Bytes added to one frame", font: { color: TEXT_DIM, size: 12 } },
        range: [0, P.capacity * 0.56],
        gridcolor: GRID,
        zeroline: false,
        tickformat: ",",
        tickfont: { color: TEXT_DIM },
      },
      yaxis: {
        tickfont: { color: TEXT, size: 12 },
        // One shared order for all the traces, not one block per group.
        categoryorder: "array",
        categoryarray: rows.map(function (r) {
          return r.label;
        }),
      },
      legend: {
        orientation: "h",
        traceorder: "normal",
        x: 0,
        y: 1,
        yanchor: "bottom",
        font: { color: TEXT_DIM },
      },
    };
    draw("dlb-actions", traces, layout);
  }

  // -------------------------------------------------------------------------
  // Chart 3 — how full each measured frame was, against the 1 MB capacity
  // -------------------------------------------------------------------------
  var STRATEGIC = "#57b36a"; // green: the one frame that does not grow with what is in view
  var FRAME_LABEL_PX = 400; // left margin: the full-settings labels
  var FIT_COL_PX = 66; // one column of the units-that-fit heatmap
  var FIT_PAD_PX = 70; // room for the bars' % labels before the heatmap

  // Units in view that fit in a frame at one flag cost: the frame with its own
  // unit flags taken out, refilled with flags of that cost. null = not measured.
  function unitsThatFit(frame, cost) {
    if (frame.flags === null || frame.flags === undefined) return null;
    return Math.max(0, Math.floor((P.capacity - (frame.used - frame.flags)) / cost.bytes));
  }

  // Fewer units fit = closer to the crash, so the scale runs red -> amber -> green.
  // Muted, like the rest of the page, so the white cell text stays readable.
  var FIT_SCALE = [
    [0, "#8f3238"],
    [0.3, "#8a6a2c"],
    [0.6, "#3f7d4e"],
    [1, "#2e9a5a"],
  ];

  function renderFrames() {
    var host = document.getElementById("dlb-frames");
    var w = host.clientWidth;
    if (!w) return; // hidden: the heatmap's share of the width is set in pixels
    var rows = P.frames.slice().reverse();
    var costs = P.flagCosts;
    var labels = rows.map(function (r) {
      return r.label;
    });
    var marginR = 12;
    var plotW = Math.max(300, w - FRAME_LABEL_PX - marginR);
    // The heatmap is a second x axis on the SAME y axis as the bars, so its rows
    // cannot drift out of line with them. Its width is fixed in pixels.
    var heatW = FIT_COL_PX * costs.length;
    var heatX0 = 1 - heatW / plotW;
    var barsX1 = heatX0 - FIT_PAD_PX / plotW;
    var icons = costs.map(function (c) {
      return String((c.bytes - costs[0].bytes) / 240);
    });
    var z = rows.map(function (r) {
      return costs.map(function (c) {
        return unitsThatFit(r, c);
      });
    });

    var bars = {
      type: "bar",
      orientation: "h",
      y: labels,
      x: rows.map(function (r) {
        return r.used;
      }),
      marker: {
        color: rows.map(function (r) {
          if (r.used > P.capacity) return OVER;
          return r.kind === "strategic" ? STRATEGIC : "#5aa9e6";
        }),
      },
      text: rows.map(function (r) {
        return pct(r.used);
      }),
      textposition: "outside",
      textfont: { color: TEXT_DIM, size: 12 },
      cliponaxis: false,
      hovertemplate: "%{y}<br>%{x:,} B (%{text} of the buffer)<extra></extra>",
    };
    var heat = {
      type: "heatmap",
      xaxis: "x2",
      x: icons,
      y: labels,
      z: z,
      colorscale: FIT_SCALE,
      showscale: false,
      xgap: 2,
      ygap: 2,
      hoverongaps: false,
      texttemplate: "%{z:,}",
      textfont: { color: "#ffffff", size: 13 },
      hovertemplate:
        "%{y}<br>%{x} promotion icons per unit on average: %{z:,} units in view fit<extra></extra>",
    };

    var heatMid = (heatX0 + 1) / 2;
    var annotations = [
      {
        x: P.capacity,
        xanchor: "right",
        yref: "paper",
        y: 1,
        yanchor: "bottom",
        text: "Capacity: 1,048,576 B",
        showarrow: false,
        font: { color: OVER, size: 12 },
      },
      {
        xref: "paper",
        x: heatMid,
        xanchor: "center",
        yref: "paper",
        y: 1,
        yanchor: "bottom",
        yshift: 40,
        text: "<b>Units in view that fit</b>",
        showarrow: false,
        font: { color: TEXT, size: 13 },
      },
      {
        xref: "paper",
        x: heatMid,
        xanchor: "center",
        yref: "paper",
        y: 1,
        yanchor: "bottom",
        yshift: 22,
        text: "by average promotion icons per unit",
        showarrow: false,
        font: { color: TEXT_DIM, size: 11 },
      },
    ];
    // A frame whose flag share was not measured has no cells: mark the gap.
    rows.forEach(function (r) {
      if (unitsThatFit(r, costs[0]) !== null) return;
      // By index, not name: a numeric-looking category name ("13") in an
      // annotation is read as a position and stretches the axis.
      icons.forEach(function (ic, i) {
        annotations.push({
          xref: "x2",
          x: i,
          yref: "y",
          y: r.label,
          text: "–",
          showarrow: false,
          font: { color: TEXT_DIM, size: 13 },
        });
      });
    });

    var layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: FRAME_LABEL_PX, r: marginR, t: 70, b: 50 },
      height: 110 + 30 * rows.length,
      font: { color: TEXT },
      showlegend: false,
      xaxis: {
        domain: [0, barsX1],
        title: { text: "Bytes in one frame", font: { color: TEXT_DIM, size: 12 } },
        range: [0, P.capacity * 1.02],
        gridcolor: GRID,
        zeroline: false,
        tickformat: ",",
        tickfont: { color: TEXT_DIM },
      },
      xaxis2: {
        domain: [heatX0, 1],
        type: "category",
        side: "top",
        fixedrange: true,
        showgrid: false,
        zeroline: false,
        ticks: "",
        tickfont: { color: TEXT, size: 13 },
      },
      yaxis: { tickfont: { color: TEXT, size: 12 }, showgrid: false },
      shapes: [
        {
          type: "line",
          x0: P.capacity,
          x1: P.capacity,
          yref: "paper",
          y0: 0,
          y1: 1,
          line: { color: OVER, width: 1.5, dash: "dash" },
        },
      ],
      annotations: annotations,
    };
    draw("dlb-frames", [bars, heat], layout);
  }

  // -------------------------------------------------------------------------
  // Table — per-item costs. Static: built once.
  // -------------------------------------------------------------------------
  function buildTable(hostId, heads, rows) {
    var host = document.getElementById(hostId);
    host.innerHTML = "";
    var table = document.createElement("table");
    table.className = "dlb-table";
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    heads.forEach(function (h) {
      var th = document.createElement("th");
      th.textContent = h.text;
      if (h.num) th.className = "dlb-num";
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    rows.forEach(function (r, ri) {
      var tr = document.createElement("tr");
      r.forEach(function (v, i) {
        var td = document.createElement("td");
        td.textContent = v;
        if (heads[i].num) td.className = "dlb-num";
        if (heads[i].shade) td.style.background = heads[i].shade(ri);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  // Heatmap shade for a cost: red whose intensity tracks the item's share of the
  // buffer relative to the largest item, sqrt-scaled so mid values stay visible
  // (as shade() in instant_yields.js, in red because a bigger share is worse).
  function costShade(bytes, max) {
    if (!max || bytes <= 0) return "transparent";
    var t = Math.sqrt(bytes / max);
    var lo = [40, 22, 26];
    var hi = [158, 52, 58];
    return (
      "rgb(" +
      Math.round(lo[0] + (hi[0] - lo[0]) * t) + "," +
      Math.round(lo[1] + (hi[1] - lo[1]) * t) + "," +
      Math.round(lo[2] + (hi[2] - lo[2]) * t) + ")"
    );
  }

  function buildTables() {
    var maxCost = Math.max.apply(
      null,
      P.itemCosts.map(function (c) {
        return c.bytes;
      })
    );
    buildTable(
      "dlb-costs-table",
      [
        { text: "Item on screen" },
        { text: "Bytes per frame", num: true },
        {
          text: "Share of the buffer",
          num: true,
          shade: function (ri) {
            return costShade(P.itemCosts[ri].bytes, maxCost);
          },
        },
        { text: "Made of" },
        { text: "Basis" },
      ],
      P.itemCosts.map(function (c) {
        return [c.item, fmtB(c.bytes), ((100 * c.bytes) / P.capacity).toFixed(2) + "%", c.makeup, c.basis];
      })
    );
  }

  function render() {
    P.scenes.forEach(renderDonut);
    renderActions();
    renderFrames();
  }

  buildDonutGrid();
  buildTables();
  render();

  // Nothing to serialize: the report has no controls, so its hash is the bare slug.
  window.DrawListBufferReport = { render: render };
  Explorer.Router.register({
    key: "draw_list_buffer",
    slug: "InterfaceDrawListBuffer",
    render: render
  });
})();
