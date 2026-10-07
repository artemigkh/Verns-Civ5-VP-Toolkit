/* Interface Draw List Buffer (dev) report — what fills the EXE's 1 MB per-frame
   interface draw list, and how much of it is left for unit flags.

   Like Process Memory, this report has no pipeline behind it: PAYLOAD.draw_list_buffer
   is assets/draw_list_buffer.json passed straight through (see its _comment for where
   the measurements come from).

   Controls (left sidebar): a mutually-exclusive Scene selector. The donut follows
   the scene; the cost table, the frame-size bars and the flag headroom bars are fixed. Modeled on civs.js (Plotly donut) and instant_yields.js
   (chip controls + router registration). */
(function () {
  "use strict";

  var P = window.PAYLOAD.draw_list_buffer;
  var Ser = Explorer.Ser;

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

  var SCENE_KEYS = P.scenes.map(function (s) {
    return s.key;
  });
  var DEF = { scene: P.defaultScene || SCENE_KEYS[0] };
  var state = { scene: DEF.scene };

  function scene() {
    for (var i = 0; i < P.scenes.length; i++) {
      if (P.scenes[i].key === state.scene) return P.scenes[i];
    }
    return P.scenes[0];
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
  // (and colour) on the ring when the scene changes.
  function sceneUsers(sc) {
    return P.users.filter(function (u) {
      return sc.users[u.key];
    });
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

  function buildSceneControls() {
    var host = document.getElementById("dlb-scene-controls");
    host.innerHTML = "";
    P.scenes.forEach(function (s) {
      host.appendChild(
        chip(s.label, s.key === state.scene, function () {
          if (state.scene === s.key) return;
          state.scene = s.key;
          buildSceneControls();
          render();
        })
      );
    });
  }

  // -------------------------------------------------------------------------
  // Chart 1 — who uses the buffer, with the unused part of the 1 MB in gray
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
      labels.push("Empty: room for units");
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
      rotation: 0,
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
      margin: { l: 110, r: 110, t: 40, b: 50 },
      height: 480,
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
          font: { color: over ? OVER : TEXT, size: 28 },
        },
      ],
    };
    draw("dlb-donut", [trace], layout);
  }

  // -------------------------------------------------------------------------
  // Chart 2 — how full each measured frame was, against the 1 MB capacity
  // -------------------------------------------------------------------------
  function renderFrames() {
    var rows = P.frames.slice().reverse();
    var trace = {
      type: "bar",
      orientation: "h",
      y: rows.map(function (r) {
        return r.label;
      }),
      x: rows.map(function (r) {
        return r.used;
      }),
      marker: {
        color: rows.map(function (r) {
          return r.used > P.capacity ? OVER : "#5aa9e6";
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
    var layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 250, r: 70, t: 28, b: 50 },
      height: 70 + 30 * rows.length,
      font: { color: TEXT },
      showlegend: false,
      xaxis: {
        title: { text: "Bytes in one frame", font: { color: TEXT_DIM, size: 12 } },
        range: [0, P.capacity * 1.12],
        gridcolor: GRID,
        zeroline: false,
        tickformat: ",",
        tickfont: { color: TEXT_DIM },
      },
      yaxis: { tickfont: { color: TEXT, size: 13 } },
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
      annotations: [
        {
          x: P.capacity,
          yref: "paper",
          y: 1,
          yanchor: "bottom",
          text: "Capacity: 1,048,576 B",
          showarrow: false,
          font: { color: OVER, size: 12 },
        },
      ],
    };
    draw("dlb-frames", [trace], layout);
  }

  // -------------------------------------------------------------------------
  // Chart 3 — how many more unit flags the empty space holds (calculated)
  // -------------------------------------------------------------------------
  var FLAG_COLORS = ["#57b36a", "#e0a458", "#e5484d"];

  function renderHeadroom() {
    var x = P.headroomScenes.map(function (s) {
      return s.label;
    });
    var traces = P.flagCosts.map(function (f, i) {
      var fit = P.headroomScenes.map(function (s) {
        return Math.max(0, Math.floor((P.capacity - s.used) / f.bytes));
      });
      return {
        type: "bar",
        name: f.label + " (" + f.bytes.toLocaleString() + " B)",
        x: x,
        y: fit,
        marker: { color: FLAG_COLORS[i % FLAG_COLORS.length] },
        text: fit.map(function (n) {
          return n.toLocaleString();
        }),
        textposition: "outside",
        textfont: { color: TEXT_DIM, size: 12 },
        cliponaxis: false,
        hovertemplate: "%{x}<br>" + f.label + ": %{y:,} more flags<extra></extra>",
      };
    });
    var layout = {
      barmode: "group",
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 70, r: 30, t: 50, b: 40 },
      height: 380,
      font: { color: TEXT },
      xaxis: { tickfont: { color: TEXT, size: 13 } },
      yaxis: {
        title: { text: "More unit flags that fit", font: { color: TEXT_DIM, size: 12 } },
        gridcolor: GRID,
        zeroline: false,
        tickfont: { color: TEXT_DIM },
      },
      legend: { orientation: "h", x: 0, y: 1.04, yanchor: "bottom", font: { color: TEXT_DIM } },
    };
    draw("dlb-headroom", traces, layout);
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
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      r.forEach(function (v, i) {
        var td = document.createElement("td");
        td.textContent = v;
        if (heads[i].num) td.className = "dlb-num";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  function buildTables() {
    buildTable(
      "dlb-costs-table",
      [
        { text: "Item on screen" },
        { text: "Bytes per frame", num: true },
        { text: "Share of the buffer", num: true },
        { text: "Made of" },
        { text: "Basis" },
      ],
      P.itemCosts.map(function (c) {
        return [c.item, fmtB(c.bytes), ((100 * c.bytes) / P.capacity).toFixed(2) + "%", c.makeup, c.basis];
      })
    );
  }

  function render() {
    var sc = scene();
    document.getElementById("dlb-scene-note").textContent = sc.note;
    renderDonut(sc);
    renderFrames();
    renderHeadroom();
    Explorer.Router.touch("draw_list_buffer");
  }

  // --- url -----------------------------------------------------------------
  function encode() {
    var p = {};
    Ser.put(p, "s", state.scene, DEF.scene);
    return p;
  }

  function decode(p) {
    // Reset before overlaying (router contract C2); control DOM only (C3).
    state.scene = Ser.strIn(p.s, SCENE_KEYS, DEF.scene);
    buildSceneControls();
  }

  buildSceneControls();
  buildTables();
  render();

  window.DrawListBufferReport = { render: render };
  Explorer.Router.register({
    key: "draw_list_buffer",
    slug: "InterfaceDrawListBuffer",
    render: render,
    encode: encode,
    decode: decode
  });
})();
