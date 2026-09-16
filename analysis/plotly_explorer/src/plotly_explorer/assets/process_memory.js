/* Process Memory (dev) report — where the whole 4,096 MB address space of a
   running Civ 5 process goes, at two benchmark points, as two donuts over one
   table.

   This is the "Who holds the memory" section of *The Civ 5 Memory Ledger*
   lifted into the explorer. It is the odd report out and marked (dev) for it:
   every other report aggregates this repo's autoplay stats DB, while these are
   one-off measurements of a live CivilizationV_DX11.exe taken in the
   Community-Patch-DLL workspace — the DLL's allocation hook, its heap and
   address-space walks, the Lua allocator profile and a VMMap capture of a
   reference game. The numbers therefore never change on a rebuild; see
   assets/process_memory.json.

   Reading the chart:

     inner ring   the owner — DLL (green), Lua (blue), video driver (red),
                  EXE and everything else (yellow), Reserved (plum), Headroom
     outer ring   the item within that owner
     unfilled     Headroom, the only part of the ring holding nothing. It is
                  split into the largest single free block and the rest,
                  because a 32-bit process dies when no ONE hole is big
                  enough, not when the total runs out

   The full circle is the whole 4,096 MB address space rather than committed
   memory, so every percentage on the page — chart labels, tooltips and table
   — has that one denominator. Reserve whose owner is known is charged to that
   owner and counted once (the DLL's minidump reserve and hook node pool, the
   driver's buffer reserve), so the plum slice is only reserve that is shared
   between owners or that nothing has claimed.

   Hatched items are estimates carried over from the reference VMMap capture.
   Hovering or focusing a segment traces it through both charts and the table.

   The layout is pure viewBox SVG, so nothing here measures laid-out geometry
   and nothing needs redrawing on resize — render() builds once and is a no-op
   after that (the router calls it on every sidebar drag frame). */
(function () {
  "use strict";

  var P = window.PAYLOAD.process_memory;
  if (!P) return;

  var C = P.colors;

  // key -> {label, desc, est}, and the item order the rings and table follow.
  var ITEM = {};
  var ORDER = [];
  P.items.forEach(function (it) {
    ITEM[it.key] = it;
    ORDER.push(it.key);
  });

  var OWNER = {};
  P.owners.forEach(function (o) {
    OWNER[o.key] = o;
  });

  // --- geometry ------------------------------------------------------------
  var VBW = 616;
  var VBH = 404;
  var CX = 312;
  var CY = 190;
  var R_IN0 = 70;
  var R_IN1 = 96; // owner ring
  var R_OUT0 = 101;
  var R_OUT1 = 148; // item ring
  var START = 50; // first slice starts here, clockwise from 12 o'clock
  var LABEL_GAP = 40; // min vertical spacing between leader labels on one side
  var LBL_TOP = 20;
  var LBL_BOT = VBH - 46; // a label's second line must clear the footnote below

  var SVG_NS = "http://www.w3.org/2000/svg";

  function pt(r, a) {
    var t = (a * Math.PI) / 180;
    return [CX + r * Math.sin(t), CY - r * Math.cos(t)];
  }

  function arc(r0, r1, a0, a1) {
    var large = a1 - a0 > 180 ? 1 : 0;
    var p0 = pt(r1, a0);
    var p1 = pt(r1, a1);
    var p2 = pt(r0, a1);
    var p3 = pt(r0, a0);
    return (
      "M" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) +
      "A" + r1 + " " + r1 + " 0 " + large + " 1 " + p1[0].toFixed(2) + " " + p1[1].toFixed(2) +
      "L" + p2[0].toFixed(2) + " " + p2[1].toFixed(2) +
      "A" + r0 + " " + r0 + " 0 " + large + " 0 " + p3[0].toFixed(2) + " " + p3[1].toFixed(2) +
      "Z"
    );
  }

  // --- formatting ----------------------------------------------------------
  function fmt(v, dec) {
    if (dec === undefined) dec = 1;
    var s = Math.abs(v).toFixed(dec);
    var bits = s.split(".");
    bits[0] = bits[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (v < 0 ? "-" : "") + bits.join(".");
  }

  function signed(v) {
    return (v >= 0 ? "+" : "-") + fmt(Math.abs(v));
  }

  function el(name, cls, text) {
    var node = document.createElement(name);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var k in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, k)) node.setAttribute(k, attrs[k]);
    }
    return node;
  }

  function sum(point, ownerKey) {
    var s = 0;
    ORDER.forEach(function (k) {
      if (k.indexOf(ownerKey + ".") === 0 && point.values[k]) s += point.values[k];
    });
    return s;
  }

  // --- trace state ---------------------------------------------------------
  // Every segment across both donuts, and every table row, keyed the same way:
  // "cat.<owner>" or "<owner>.<item>". Held as arrays rather than re-queried,
  // so highlighting never touches the DOM tree.
  var segs = [];
  var rows = {};
  var host = null;
  var tip = null;

  function trace(key) {
    if (!host) return;
    host.classList.add("pm-tracing");
    var cat = key.indexOf("cat.") === 0 ? key.slice(4) : null;
    segs.forEach(function (s) {
      var on = s.key === key || (cat && s.key.indexOf(cat + ".") === 0);
      if (on) s.el.classList.add("on");
      else s.el.classList.remove("on");
    });
    for (var k in rows) {
      if (!Object.prototype.hasOwnProperty.call(rows, k)) continue;
      var lit = k === key || (cat && k.indexOf(cat + ".") === 0);
      if (lit) rows[k].classList.add("on");
      else rows[k].classList.remove("on");
    }
  }

  function clearTrace() {
    if (!host) return;
    host.classList.remove("pm-tracing");
    segs.forEach(function (s) {
      s.el.classList.remove("on");
    });
    for (var k in rows) {
      if (Object.prototype.hasOwnProperty.call(rows, k)) rows[k].classList.remove("on");
    }
    if (tip) tip.hidden = true;
  }

  // --- tooltip -------------------------------------------------------------
  function showTip(seg, x, y) {
    if (!tip) return;
    var meta = seg.key.indexOf("cat.") === 0 ? OWNER[seg.key.slice(4)] : ITEM[seg.key];
    var pct = (100 * seg.value) / seg.point.space;
    tip.textContent = "";
    tip.appendChild(el("b", null, meta.label || meta.name));
    tip.appendChild(
      el(
        "span", "pm-tip-v",
        fmt(seg.value) + " MB · " + pct.toFixed(1) + "% of the address space" +
        (meta.est ? " · estimated" : "")
      )
    );
    tip.appendChild(el("span", "pm-tip-d", seg.point.title + ", " + seg.point.sub));
    tip.appendChild(el("span", "pm-tip-d", meta.desc));
    tip.hidden = false;

    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var left = Math.min(x + 14, window.innerWidth - w - 12);
    var top = y + 16 + h > window.innerHeight ? y - h - 12 : y + 16;
    tip.style.left = Math.max(12, left) + "px";
    tip.style.top = Math.max(12, top) + "px";
    trace(seg.key);
  }

  function wire(seg) {
    segs.push(seg);
    seg.el.addEventListener("pointermove", function (e) {
      showTip(seg, e.clientX, e.clientY);
    });
    seg.el.addEventListener("pointerleave", clearTrace);
    seg.el.addEventListener("focus", function () {
      var r = seg.el.getBoundingClientRect();
      showTip(seg, r.left + r.width / 2, r.top + r.height / 2);
    });
    seg.el.addEventListener("blur", clearTrace);
  }

  // --- donut ---------------------------------------------------------------
  // `empty` owners (headroom) get no fill and an outline instead: the ring
  // should look like it is holding nothing there, because it is.
  function segment(svg, point, key, value, d, aria) {
    var isCat = key.indexOf("cat.") === 0;
    var owner = OWNER[isCat ? key.slice(4) : key.split(".")[0]];
    var attrs = { class: "pm-seg", d: d, tabindex: "0", role: "img", "aria-label": aria };
    if (owner.empty) attrs.class += " pm-empty";
    else attrs.fill = isCat ? C["cat-" + owner.key] : C[key];
    var path = svgEl("path", attrs);
    svg.appendChild(path);
    wire({ el: path, key: key, value: value, point: point });
    return path;
  }

  function donut(point) {
    var total = point.space; // the full circle is the whole address space
    var svg = svgEl("svg", { viewBox: "0 0 " + VBW + " " + VBH });
    // <title> names the chart for AT. No role="img" on the root: that would
    // hide the children, and every segment carries its own aria-label.
    var caption = svgEl("title", {});
    caption.textContent =
      point.title + ", " + point.sub + ": the whole " + fmt(total, 0) + " MB address space. " +
      P.owners.map(function (o) {
        return o.name + " " + ((100 * sum(point, o.key)) / total).toFixed(1) + "%";
      }).join("; ");
    svg.appendChild(caption);

    // Hatch for the estimated items. The pattern id has to be unique per donut
    // or the second chart's <defs> wins for both.
    var pid = "pm-hatch-" + point.key;
    var defs = svgEl("defs", {});
    var pat = svgEl("pattern", {
      id: pid,
      width: "5",
      height: "5",
      patternUnits: "userSpaceOnUse",
      patternTransform: "rotate(45)"
    });
    pat.appendChild(svgEl("line", { x1: "0", y1: "0", x2: "0", y2: "5", class: "pm-hatch-line" }));
    defs.appendChild(pat);
    svg.appendChild(defs);

    var a = START;
    var labels = [];
    var hatches = [];

    P.owners.forEach(function (cat) {
      var keys = ORDER.filter(function (k) {
        return k.indexOf(cat.key + ".") === 0 && point.values[k] > 0;
      });
      if (!keys.length) return;
      var csum = 0;
      var a0 = a;
      keys.forEach(function (k) {
        var v = point.values[k];
        csum += v;
        var span = (360 * v) / total;
        var d = arc(R_OUT0, R_OUT1, a, a + span);
        var meta = ITEM[k];
        segment(svg, point, k, v, d, meta.label + ": " + fmt(v) + " MB" + (meta.est ? ", estimated" : ""));
        if (meta.est) hatches.push(svgEl("path", { d: d, fill: "url(#" + pid + ")", class: "pm-hatch" }));
        a += span;
      });
      segment(svg, point, "cat." + cat.key, csum, arc(R_IN0, R_IN1, a0, a), cat.name + ": " + fmt(csum) + " MB");
      labels.push({
        name: cat.name,
        line2: ((100 * csum) / total).toFixed(1) + "% · " + fmt(csum, 0) + " MB",
        mid: (a0 + a) / 2
      });
    });

    hatches.forEach(function (h) {
      svg.appendChild(h); // over the fills; pointer-events off, so it never steals a hover
    });

    // Leader labels, pushed apart vertically within each side so six of them
    // never overlap when a category is a thin sliver. Pushing only ever moves a
    // label DOWN, so a big bottom category (EXE sits near 6 o'clock) can walk
    // into the footnote — hence the second pass, which slides the whole side
    // back up by the overflow rather than clamping one label onto its neighbour.
    var placed = labels.map(function (l) {
      var p = pt(R_OUT1 + 16, l.mid);
      return { l: l, x: p[0], y: p[1], side: Math.sin((l.mid * Math.PI) / 180) >= 0 ? 1 : -1 };
    });
    [1, -1].forEach(function (side) {
      var grp = placed.filter(function (p) {
        return p.side === side;
      });
      if (!grp.length) return;
      grp.sort(function (u, v) {
        return u.y - v.y;
      });
      for (var i = 1; i < grp.length; i++) {
        if (grp[i].y - grp[i - 1].y < LABEL_GAP) grp[i].y = grp[i - 1].y + LABEL_GAP;
      }
      var over = grp[grp.length - 1].y - LBL_BOT;
      if (over > 0) {
        var shift = Math.min(over, grp[0].y - LBL_TOP);
        if (shift > 0) {
          grp.forEach(function (p) {
            p.y -= shift;
          });
        }
      }
    });
    placed.forEach(function (p) {
      var e = pt(R_OUT1 + 3, p.l.mid);
      var tx = p.x + p.side * 8;
      svg.appendChild(
        svgEl("polyline", {
          class: "pm-leader",
          points:
            e[0].toFixed(1) + "," + e[1].toFixed(1) + " " +
            p.x.toFixed(1) + "," + p.y.toFixed(1) + " " +
            (tx - p.side * 2).toFixed(1) + "," + p.y.toFixed(1)
        })
      );
      var anchor = p.side > 0 ? "start" : "end";
      var name = svgEl("text", {
        class: "pm-lbl-name",
        x: tx.toFixed(1),
        y: (p.y - 3).toFixed(1),
        "text-anchor": anchor
      });
      name.textContent = p.l.name;
      var val = svgEl("text", {
        class: "pm-lbl-val",
        x: tx.toFixed(1),
        y: (p.y + 14).toFixed(1),
        "text-anchor": anchor
      });
      val.textContent = p.l.line2;
      svg.appendChild(name);
      svg.appendChild(val);
    });

    // Centre: the constant 4,096, and how much of it is still unclaimed.
    var big = svgEl("text", { class: "pm-ctr-big", x: CX, y: CY - 8, "text-anchor": "middle" });
    big.textContent = fmt(total, 0);
    var small = svgEl("text", { class: "pm-ctr-small", x: CX, y: CY + 12, "text-anchor": "middle" });
    small.textContent = "MB OF ADDRESS SPACE";
    var note = svgEl("text", { class: "pm-ctr-note", x: CX, y: CY + 32, "text-anchor": "middle" });
    note.textContent = fmt(point.free, 0) + " MB still free";
    svg.appendChild(big);
    svg.appendChild(small);
    svg.appendChild(note);

    // Under the ring: the fragmentation caveat on that free total.
    var foot = svgEl("text", { class: "pm-ctr-note", x: CX, y: VBH - 12, "text-anchor": "middle" });
    foot.textContent =
      "headroom is " + fmt(point.holes, 0) + " holes — the largest is " +
      fmt(point.values["free.largest"], 0) + " MB";
    svg.appendChild(foot);

    var card = el("figure", "pm-card pm-donut-card");
    var head = el("div", "pm-donut-head");
    head.appendChild(el("h3", null, point.title + " · " + point.sub));
    head.appendChild(el("span", "pm-mono", point.meta));
    card.appendChild(head);
    card.appendChild(svg);
    return card;
  }

  // --- table ---------------------------------------------------------------
  function swatch(key, owner) {
    var s = el("span", "pm-sw" + (owner.empty ? " pm-sw-empty" : ""));
    if (!owner.empty) s.style.background = C[key];
    return s;
  }

  function nameCell(swatchNode, label, desc, estFlag) {
    var td = el("td");
    if (swatchNode) td.appendChild(swatchNode);
    td.appendChild(document.createTextNode(label));
    if (estFlag) td.appendChild(el("span", "pm-est", "est."));
    if (desc) td.appendChild(el("span", "pm-sub", desc));
    return td;
  }

  function num(text, cls) {
    return el("td", "pm-n" + (cls ? " " + cls : ""), text);
  }

  function table(pts) {
    var a = pts[0];
    var b = pts[1];
    var t = el("table", "pm-table");

    // The table runs to ~47 rows, so the column labels are off screen for most
    // of it. They are repeated above every owner section rather than made
    // sticky: .pm-scroll carries overflow-x for narrow panes, which makes it a
    // scroll container on BOTH axes, and a sticky header inside it would anchor
    // to that container instead of the page.
    var HEAD = [
      "Owner and item",
      a.title + " " + a.sub + " MB",
      "% of space",
      b.title + " " + b.sub + " MB",
      "% of space",
      "Change MB"
    ];

    function headerRow(tag, cls) {
      var tr = el("tr", cls);
      HEAD.forEach(function (label, i) {
        tr.appendChild(el(tag, i ? "pm-n" : null, label));
      });
      return tr;
    }

    var thead = el("thead");
    thead.appendChild(headerRow("th", null));
    t.appendChild(thead);

    var tbody = el("tbody");

    function pairCells(tr, va, vb, est) {
      // A value absent at one point (map generation, loaded-save data) leaves
      // its cell blank rather than showing 0.0, and suppresses the change.
      [[va, a], [vb, b]].forEach(function (p) {
        if (p[0] === null) {
          tr.appendChild(num("–"));
          tr.appendChild(num(""));
        } else {
          tr.appendChild(num((est ? "≈" : "") + fmt(p[0])));
          tr.appendChild(num(((100 * p[0]) / p[1].space).toFixed(1)));
        }
      });
      tr.appendChild(num(va === null || vb === null ? "" : signed(vb - va)));
    }

    P.owners.forEach(function (cat, ci) {
      // Not before the first section — <thead> is still right above it. The
      // repeats are decoration over the real header, so they are hidden from
      // assistive tech rather than announced as a second set of column headers.
      if (ci) {
        var rehead = headerRow("td", "pm-rehead");
        rehead.setAttribute("aria-hidden", "true");
        tbody.appendChild(rehead);
      }
      var ctr = el("tr", "pm-cat");
      ctr.setAttribute("data-key", "cat." + cat.key);
      ctr.appendChild(nameCell(swatch("cat-" + cat.key, cat), cat.name, cat.desc, false));
      pairCells(ctr, sum(a, cat.key), sum(b, cat.key), false);
      tbody.appendChild(ctr);
      rows["cat." + cat.key] = ctr;

      ORDER.forEach(function (k) {
        if (k.indexOf(cat.key + ".") !== 0) return;
        var va = a.values[k];
        var vb = b.values[k];
        if (!va && !vb) return;
        var meta = ITEM[k];
        var tr = el("tr", "pm-item");
        tr.setAttribute("data-key", k);
        tr.appendChild(nameCell(swatch(k, cat), meta.label, meta.desc, !!meta.est));
        pairCells(tr, va === undefined ? null : va, vb === undefined ? null : vb, !!meta.est);
        tbody.appendChild(tr);
        rows[k] = tr;
      });
    });

    // The ring sums to the whole address space, so the total is a constant and
    // the interesting movement is in the three-way split underneath it.
    var tot = el("tr", "pm-total");
    tot.appendChild(el("td", null, "Address space"));
    tot.appendChild(num(fmt(a.space)));
    tot.appendChild(num("100.0"));
    tot.appendChild(num(fmt(b.space)));
    tot.appendChild(num("100.0"));
    tot.appendChild(num(signed(b.space - a.space)));
    tbody.appendChild(tot);

    [["of which committed", "committed"], ["of which reserved", "reserved"], ["of which free", "free"]].forEach(
      function (pair) {
        var tr = el("tr", "pm-soft");
        tr.appendChild(el("td", null, pair[0]));
        tr.appendChild(num(fmt(a[pair[1]])));
        tr.appendChild(num(((100 * a[pair[1]]) / a.space).toFixed(1)));
        tr.appendChild(num(fmt(b[pair[1]])));
        tr.appendChild(num(((100 * b[pair[1]]) / b.space).toFixed(1)));
        tr.appendChild(num(signed(b[pair[1]] - a[pair[1]])));
        tbody.appendChild(tr);
      }
    );

    t.appendChild(tbody);

    for (var k in rows) {
      if (!Object.prototype.hasOwnProperty.call(rows, k)) continue;
      (function (key, tr) {
        tr.addEventListener("pointerenter", function () {
          trace(key);
        });
        tr.addEventListener("pointerleave", clearTrace);
      })(k, rows[k]);
    }
    return t;
  }

  // --- footnotes -----------------------------------------------------------
  // Two notes under the charts, and nothing else in prose: the table below
  // carries every other figure, so a paragraph restating it would only be one
  // more place for a number to go stale.
  function note(parts) {
    var p = el("p", "pm-note");
    parts.forEach(function (bit) {
      if (typeof bit === "string") p.appendChild(document.createTextNode(bit));
      else p.appendChild(el("strong", null, bit[0]));
    });
    return p;
  }

  function pct(v, point) {
    return ((100 * v) / point.space).toFixed(1);
  }

  // Why the plum slice is smaller than the "of which reserved" row underneath
  // it. Without this the two disagree by the owner-charged reserve and look
  // like an error.
  function reservedNote() {
    return note([
      ["Reserved memory holds nothing."],
      " It is address space that has been spoken for and never backed with pages: invisible in " +
        "Task Manager, yet no other allocation can use those addresses. In a 32-bit process " +
        "address space, not physical memory, is what runs out. Where the owner is known the " +
        "reserve is charged to that owner rather than to the reserved slice, and counted once: " +
        "the DLL's minidump reserve and its hook node pool are green, the driver's buffer " +
        "reserve red. What stays in the plum slice is reserve that is shared between owners, or " +
        "that nothing has claimed."
    ]);
  }

  // Computed from the data rather than hard-coded, so it cannot drift from the
  // DLL row in the table.
  function dllNote(a, b) {
    var dllA = sum(a, "dll");
    var dllB = sum(b, "dll");
    return note([
      ["The DLL grows from " + fmt(dllA, 0) + " to " + fmt(dllB, 0) + " MB"],
      " (" + pct(dllA, a) + "% to " + pct(dllB, b) + "% of the address space), led by danger " +
        "plots and loaded-save data."
    ]);
  }

  // --- render --------------------------------------------------------------
  var built = false;

  function render() {
    if (built) return;
    host = document.getElementById("pm-body");
    if (!host) return;
    host.textContent = "";
    segs = [];
    rows = {};

    var pts = P.points;

    var donuts = el("div", "pm-donuts");
    pts.forEach(function (point) {
      donuts.appendChild(donut(point));
    });
    host.appendChild(donuts);

    var key = el("div", "pm-key");
    var k1 = el("span");
    k1.appendChild(el("i", "pm-k-hatch"));
    k1.appendChild(document.createTextNode("Estimated from the reference capture"));
    key.appendChild(k1);
    var k2 = el("span");
    k2.appendChild(el("i", "pm-k-empty"));
    k2.appendChild(document.createTextNode("Headroom: unclaimed address space"));
    key.appendChild(k2);
    key.appendChild(el("span", null, "Hover or focus a segment or row to trace it in both charts"));
    host.appendChild(key);

    var notes = el("div", "pm-notes");
    notes.appendChild(reservedNote());
    notes.appendChild(dllNote(pts[0], pts[1]));
    host.appendChild(notes);

    var scroll = el("div", "pm-scroll");
    scroll.appendChild(table(pts));
    host.appendChild(scroll);

    tip = document.getElementById("pm-tip");
    built = true;
  }

  render();

  window.ProcessMemoryReport = { render: render };
  Explorer.Router.register({
    key: "process_memory",
    slug: "ProcessMemory",
    render: render
  });
})();
