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

   ---------------------------------------------------------------------------
   Everything the reader can change lives in `state` and round-trips through
   the URL (see encode/decode at the tail, and router.js's four clauses):

     sticky     pin the charts to the top of the pane. The table is ~47 rows,
                so without this the chart you are lighting up by hovering a row
                has long scrolled away — which is the whole point of the trace.
     compact    drop the per-item descriptions, taking the table from ~2,800px
                to ~1,200px when you are scanning numbers rather than reading.
     sort       reorder items WITHIN each owner section by any numeric column.
                Sorting across sections would destroy the owner grouping, which
                is the table's spine.
     collapsed  fold an owner down to its summary row.
     pinned     hold one trace lit while the pointer goes elsewhere.

   The DOM is built once; every one of those is applied by applyView() moving
   rows and toggling classes, so no interaction rebuilds the charts. */
(function () {
  "use strict";

  var P = window.PAYLOAD.process_memory;
  if (!P) return;

  var C = P.colors;
  var Ser = Explorer.Ser;

  // key -> {label, desc, est}, and the item order the rings and table follow.
  var ITEM = {};
  var ORDER = [];
  P.items.forEach(function (it) {
    ITEM[it.key] = it;
    ORDER.push(it.key);
  });

  var OWNER = {};
  var OWNER_KEYS = [];
  P.owners.forEach(function (o) {
    OWNER[o.key] = o;
    OWNER_KEYS.push(o.key);
  });

  // Every key a trace or a pin can name, for validating a pasted hash.
  var ALL_KEYS = OWNER_KEYS.map(function (k) {
    return "cat." + k;
  }).concat(ORDER);

  // --- state ---------------------------------------------------------------
  var state = {
    sticky: false,
    compact: false,
    sort: null, // {col: 1..5, dir: "desc"|"asc"}; null = payload order
    pinned: null,
    collapsed: new Set()
  };

  // Column indices into a row's numeric values, matching the header order.
  var COL_A_MB = 1;
  var COL_A_PCT = 2;
  var COL_B_MB = 3;
  var COL_B_PCT = 4;
  var COL_CHANGE = 5;

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

  function labelOf(key) {
    var meta = key.indexOf("cat.") === 0 ? OWNER[key.slice(4)] : ITEM[key];
    return meta ? meta.label || meta.name : key;
  }

  // --- trace + pin ---------------------------------------------------------
  // Every segment across both donuts, and every table row, keyed the same way:
  // "cat.<owner>" or "<owner>.<item>". Held as arrays rather than re-queried,
  // so highlighting never touches the DOM tree.
  var segs = [];
  var donutSegs = {}; // point key -> segment elements, for arrow-key roving
  var rows = {};
  var host = null;
  var tip = null;

  function lightKey(key) {
    if (!host) return;
    host.classList.add("pm-tracing");
    var cat = key.indexOf("cat.") === 0 ? key.slice(4) : null;
    var pinned = state.pinned === key;
    segs.forEach(function (s) {
      var on = s.key === key || (cat && s.key.indexOf(cat + ".") === 0);
      s.el.classList.toggle("on", !!on);
      s.el.classList.toggle("pinned", !!on && pinned);
    });
    for (var k in rows) {
      if (!Object.prototype.hasOwnProperty.call(rows, k)) continue;
      var lit = k === key || (cat && k.indexOf(cat + ".") === 0);
      rows[k].classList.toggle("on", lit);
      rows[k].classList.toggle("pinned", lit && pinned);
    }
  }

  function unlight() {
    if (!host) return;
    host.classList.remove("pm-tracing");
    segs.forEach(function (s) {
      s.el.classList.remove("on");
      s.el.classList.remove("pinned");
    });
    for (var k in rows) {
      if (!Object.prototype.hasOwnProperty.call(rows, k)) continue;
      rows[k].classList.remove("on");
      rows[k].classList.remove("pinned");
    }
  }

  // "Stop previewing." Falls back to the pinned trace rather than to nothing,
  // which is what lets you hover a segment, pin it, and then go read the table
  // without the highlight dropping out from under you.
  function restTrace() {
    if (state.pinned) lightKey(state.pinned);
    else unlight();
  }

  function hideTip() {
    if (tip) tip.hidden = true;
  }

  function setPinned(key) {
    state.pinned = key;
    updatePinChip();
    restTrace();
    touch();
  }

  function togglePin(key) {
    setPinned(state.pinned === key ? null : key);
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
    tip.appendChild(
      el("span", "pm-tip-hint", state.pinned === seg.key ? "click to unpin" : "click to pin")
    );
    tip.hidden = false;

    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var left = Math.min(x + 14, window.innerWidth - w - 12);
    var top = y + 16 + h > window.innerHeight ? y - h - 12 : y + 16;
    tip.style.left = Math.max(12, left) + "px";
    tip.style.top = Math.max(12, top) + "px";
    lightKey(seg.key);
  }

  function wire(seg) {
    segs.push(seg);
    seg.el.addEventListener("pointermove", function (e) {
      showTip(seg, e.clientX, e.clientY);
    });
    seg.el.addEventListener("pointerleave", function () {
      hideTip();
      restTrace();
    });
    seg.el.addEventListener("focus", function () {
      var r = seg.el.getBoundingClientRect();
      showTip(seg, r.left + r.width / 2, r.top + r.height / 2);
    });
    seg.el.addEventListener("blur", function () {
      hideTip();
      restTrace();
    });
    seg.el.addEventListener("click", function () {
      togglePin(seg.key);
      showTip(seg, seg.el.getBoundingClientRect().left, seg.el.getBoundingClientRect().top);
    });
  }

  // --- donut ---------------------------------------------------------------
  // `empty` owners (headroom) get no fill and an outline instead: the ring
  // should look like it is holding nothing there, because it is.
  function segment(svg, point, key, value, d, aria) {
    var isCat = key.indexOf("cat.") === 0;
    var owner = OWNER[isCat ? key.slice(4) : key.split(".")[0]];
    // tabindex -1 by default: see rove(). 86 segments would otherwise be 86
    // stops between the charts and the table.
    var attrs = { class: "pm-seg", d: d, tabindex: "-1", role: "img", "aria-label": aria };
    if (owner.empty) attrs.class += " pm-empty";
    else attrs.fill = isCat ? C["cat-" + owner.key] : C[key];
    var path = svgEl("path", attrs);
    svg.appendChild(path);
    wire({ el: path, key: key, value: value, point: point });
    (donutSegs[point.key] = donutSegs[point.key] || []).push(path);
    return path;
  }

  // One tab stop per chart, arrows to move inside it — the roving-tabindex
  // pattern. Without it the two donuts cost 86 presses to tab past.
  function rove(svg, point) {
    var list = donutSegs[point.key];
    if (!list || !list.length) return;
    list[0].setAttribute("tabindex", "0");
    svg.addEventListener("keydown", function (e) {
      var i = list.indexOf(document.activeElement);
      if (i < 0) return;
      var next = i;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (i + 1) % list.length;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (i - 1 + list.length) % list.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = list.length - 1;
      else if (e.key === "Enter" || e.key === " ") {
        togglePin(list[i].getAttribute("data-key"));
        e.preventDefault();
        return;
      } else return;
      e.preventDefault();
      list[i].setAttribute("tabindex", "-1");
      list[next].setAttribute("tabindex", "0");
      list[next].focus();
    });
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
        var path = segment(
          svg, point, k, v, d,
          meta.label + ": " + fmt(v) + " MB" + (meta.est ? ", estimated" : "")
        );
        path.setAttribute("data-key", k);
        if (meta.est) hatches.push(svgEl("path", { d: d, fill: "url(#" + pid + ")", class: "pm-hatch" }));
        a += span;
      });
      var catPath = segment(
        svg, point, "cat." + cat.key, csum, arc(R_IN0, R_IN1, a0, a),
        cat.name + ": " + fmt(csum) + " MB"
      );
      catPath.setAttribute("data-key", "cat." + cat.key);
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

    rove(svg, point);

    var card = el("figure", "pm-card pm-donut-card");
    var head = el("div", "pm-donut-head");
    head.appendChild(el("h3", null, point.title + " · " + point.sub));
    head.appendChild(el("span", "pm-mono", point.meta));
    card.appendChild(head);
    card.appendChild(svg);
    return card;
  }

  // --- table ---------------------------------------------------------------
  // Diverging tint behind the Change column, scored good/bad rather than
  // down/up — because the sign does not mean the same thing in every row.
  //
  // Most rows measure memory HELD, so growing is the bad direction. The
  // Headroom section measures what is LEFT, so losing it is the bad direction:
  // free.largest falling 1,134 -> 128 MB is the single worst number in the
  // table, and a purely directional ramp would paint it the same calm colour as
  // an owner giving memory back.
  //
  // Red/teal rather than red/green: same diverging reading, without the
  // red-green pair that the most common colour vision deficiency flattens.
  //
  // sqrt on the magnitude because the range spans four orders (0.1 MB to
  // 1,007 MB) and a linear ramp would leave everything but the top few rows
  // indistinguishable from zero.
  var HEAT_BAD = "226,104,80";
  var HEAT_GOOD = "72,188,186";
  var heatMax = 0;

  // +1: the row measures memory held, so a rise is bad.
  // -1: the row measures room left, so a fall is bad.
  function polarityOf(ownerKey) {
    return ownerKey === "free" ? -1 : 1;
  }

  function heatOf(v, pol) {
    if (v === null || v === undefined || !heatMax || !v) return "transparent";
    var t = Math.sqrt(Math.abs(v) / heatMax);
    var bad = v * pol > 0;
    return "rgba(" + (bad ? HEAT_BAD : HEAT_GOOD) + "," + (0.07 + 0.36 * t).toFixed(3) + ")";
  }

  var sections = []; // {owner, rehead, catRow, items: [{key, tr, vals}]}
  var tbodyEl = null;
  var footRows = [];
  var headerRows = []; // every header row, real and repeated, for sort arrows

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

  // vals is [_, aMB, aPct, bMB, bPct, change] with nulls where a point has no
  // value; index 0 is unused so an index matches its column number.
  function valueCells(tr, a, b, va, vb, est) {
    var vals = [null, null, null, null, null, null];
    [[va, a, COL_A_MB], [vb, b, COL_B_MB]].forEach(function (p) {
      if (p[0] === null) {
        tr.appendChild(num("–"));
        tr.appendChild(num(""));
      } else {
        vals[p[2]] = p[0];
        vals[p[2] + 1] = (100 * p[0]) / p[1].space;
        tr.appendChild(num((est ? "≈" : "") + fmt(p[0])));
        tr.appendChild(num(vals[p[2] + 1].toFixed(1)));
      }
    });
    var change = va === null || vb === null ? null : vb - va;
    vals[COL_CHANGE] = change;
    tr.appendChild(num(change === null ? "" : signed(change), "pm-change"));
    return vals;
  }

  function table(pts) {
    var a = pts[0];
    var b = pts[1];
    var t = el("table", "pm-table");

    // The table runs to ~47 rows, so the column labels are off screen for most
    // of it. They are repeated above every owner section rather than made
    // sticky: .pm-scroll carries overflow-x for narrow panes, which makes it a
    // scroll container on BOTH axes, and a sticky header inside it would anchor
    // to that container instead of the page. The repeats are real <th> rather
    // than decoration, because they are also the sort handles — with the charts
    // stuck to the top, <thead> is often the one header NOT on screen.
    var HEAD = [
      "Owner and item",
      a.title + " " + a.sub + " MB",
      "% of space",
      b.title + " " + b.sub + " MB",
      "% of space",
      "Change MB"
    ];

    function headerRow(cls) {
      var tr = el("tr", cls);
      HEAD.forEach(function (label, i) {
        var th = el("th", i ? "pm-n" : null);
        th.setAttribute("scope", "col");
        if (i) {
          // Sortable: a button rather than a click handler on the <th>, so it
          // is reachable and operable from the keyboard for free.
          var btn = el("button", "pm-sortbtn");
          btn.type = "button";
          btn.appendChild(document.createTextNode(label));
          btn.appendChild(el("span", "pm-sortarrow"));
          btn.setAttribute("data-col", String(i));
          btn.addEventListener("click", function () {
            cycleSort(i);
          });
          th.appendChild(btn);
        } else {
          th.textContent = label;
        }
        tr.appendChild(th);
      });
      headerRows.push(tr);
      return tr;
    }

    var thead = el("thead");
    thead.appendChild(headerRow(null));
    t.appendChild(thead);

    var tbody = el("tbody");
    tbodyEl = tbody;

    P.owners.forEach(function (cat, ci) {
      // Not before the first section — <thead> is still right above it.
      var rehead = ci ? headerRow("pm-rehead") : null;
      if (rehead) tbody.appendChild(rehead);

      var ctr = el("tr", "pm-cat");
      ctr.setAttribute("data-key", "cat." + cat.key);
      var nc = nameCell(swatch("cat-" + cat.key, cat), cat.name, cat.desc, false);
      // Disclosure first in the cell so the owner names line up whether or not
      // a section is folded.
      var disc = el("button", "pm-disc");
      disc.type = "button";
      disc.setAttribute("data-owner", cat.key);
      disc.setAttribute("aria-label", "Collapse " + cat.name);
      disc.addEventListener("click", function (e) {
        e.stopPropagation(); // the row itself pins; the button folds
        toggleCollapsed(cat.key);
      });
      nc.insertBefore(disc, nc.firstChild);
      ctr.appendChild(nc);
      var catVals = valueCells(ctr, a, b, sum(a, cat.key), sum(b, cat.key), false);
      tbody.appendChild(ctr);
      rows["cat." + cat.key] = ctr;

      var items = [];
      ORDER.forEach(function (k) {
        if (k.indexOf(cat.key + ".") !== 0) return;
        var va = a.values[k];
        var vb = b.values[k];
        if (!va && !vb) return;
        var meta = ITEM[k];
        var tr = el("tr", "pm-item");
        tr.setAttribute("data-key", k);
        tr.appendChild(nameCell(swatch(k, cat), meta.label, meta.desc, !!meta.est));
        var vals = valueCells(
          tr, a, b,
          va === undefined ? null : va,
          vb === undefined ? null : vb,
          !!meta.est
        );
        tbody.appendChild(tr);
        rows[k] = tr;
        items.push({ key: k, tr: tr, vals: vals });
      });

      sections.push({ owner: cat, rehead: rehead, catRow: ctr, catVals: catVals, items: items });
    });

    // The ring sums to the whole address space, so the total is a constant and
    // the interesting movement is in the three-way split underneath it.
    var tot = el("tr", "pm-total");
    tot.appendChild(el("td", null, "Address space"));
    tot.appendChild(num(fmt(a.space)));
    tot.appendChild(num("100.0"));
    tot.appendChild(num(fmt(b.space)));
    tot.appendChild(num("100.0"));
    tot.appendChild(num(signed(b.space - a.space), "pm-change"));
    tbody.appendChild(tot);
    // The address space is a constant, so its change is 0 and never tints; the
    // polarity is nominal.
    footRows.push({ tr: tot, change: b.space - a.space, pol: 1 });

    // Committed and reserved are memory held; free is room left, so it scores
    // the other way round — same split as the Headroom section above.
    [
      ["of which committed", "committed", 1],
      ["of which reserved", "reserved", 1],
      ["of which free", "free", -1]
    ].forEach(function (row) {
      var tr = el("tr", "pm-soft");
      tr.appendChild(el("td", null, row[0]));
      tr.appendChild(num(fmt(a[row[1]])));
      tr.appendChild(num(((100 * a[row[1]]) / a.space).toFixed(1)));
      tr.appendChild(num(fmt(b[row[1]])));
      tr.appendChild(num(((100 * b[row[1]]) / b.space).toFixed(1)));
      tr.appendChild(num(signed(b[row[1]] - a[row[1]]), "pm-change"));
      tbody.appendChild(tr);
      footRows.push({ tr: tr, change: b[row[1]] - a[row[1]], pol: row[2] });
    });

    t.appendChild(tbody);

    // One scale across owner rows, item rows and the footer, so a given tint
    // means the same number of MB wherever it appears.
    function bump(v) {
      if (v !== null && v !== undefined) heatMax = Math.max(heatMax, Math.abs(v));
    }
    sections.forEach(function (sec) {
      bump(sec.catVals[COL_CHANGE]);
      sec.items.forEach(function (it) {
        bump(it.vals[COL_CHANGE]);
      });
    });
    footRows.forEach(function (f) {
      bump(f.change);
    });
    paintHeat();

    for (var k in rows) {
      if (!Object.prototype.hasOwnProperty.call(rows, k)) continue;
      (function (key, tr) {
        tr.addEventListener("pointerenter", function () {
          lightKey(key);
        });
        tr.addEventListener("pointerleave", restTrace);
        tr.addEventListener("click", function () {
          togglePin(key);
        });
      })(k, rows[k]);
    }
    return t;
  }

  function paintHeat() {
    sections.forEach(function (sec) {
      var pol = polarityOf(sec.owner.key);
      setHeat(sec.catRow, sec.catVals[COL_CHANGE], pol);
      sec.items.forEach(function (it) {
        setHeat(it.tr, it.vals[COL_CHANGE], pol);
      });
    });
    footRows.forEach(function (f) {
      setHeat(f.tr, f.change, f.pol);
    });
  }

  function setHeat(tr, v, pol) {
    var cell = tr.querySelector(".pm-change");
    if (cell) cell.style.setProperty("--pm-heat", heatOf(v, pol));
  }

  // --- sorting -------------------------------------------------------------
  // Desc -> asc -> back to payload order. The third state matters: the payload
  // order is itself meaningful (it is the ring order), so there has to be a way
  // back to it that is not "reload the page".
  function cycleSort(col) {
    if (!state.sort || state.sort.col !== col) state.sort = { col: col, dir: "desc" };
    else if (state.sort.dir === "desc") state.sort = { col: col, dir: "asc" };
    else state.sort = null;
    applyView();
    touch();
  }

  function sortedItems(sec) {
    if (!state.sort) return sec.items;
    var col = state.sort.col;
    var sign = state.sort.dir === "asc" ? 1 : -1;
    return sec.items.slice().sort(function (x, y) {
      var xv = x.vals[col];
      var yv = y.vals[col];
      // A row with no value at this point sorts last in either direction: it is
      // absent, not zero, and the table already says so with a dash.
      if (xv === null && yv === null) return 0;
      if (xv === null) return 1;
      if (yv === null) return -1;
      return (xv - yv) * sign || (x.key < y.key ? -1 : 1);
    });
  }

  // --- collapse ------------------------------------------------------------
  function toggleCollapsed(ownerKey) {
    if (state.collapsed.has(ownerKey)) state.collapsed["delete"](ownerKey);
    else state.collapsed.add(ownerKey);
    applyView();
    touch();
  }

  function setAllCollapsed(on) {
    state.collapsed = new Set(on ? OWNER_KEYS : []);
    applyView();
    touch();
  }

  // --- controls ------------------------------------------------------------
  var pinChip = null;

  function chip(label, onClick, title) {
    var b = el("button", "chip", label);
    b.type = "button";
    if (title) b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }

  function buildControls() {
    var charts = document.getElementById("pm-chart-controls");
    var tableC = document.getElementById("pm-table-controls");
    var secC = document.getElementById("pm-section-controls");
    var exportC = document.getElementById("pm-export-controls");
    if (!charts || !tableC || !secC || !exportC) return;

    charts.textContent = "";
    charts.appendChild(
      chip("Stick to top", function () {
        state.sticky = !state.sticky;
        applyView();
        touch();
      }, "Keep the charts in view while the table scrolls, so a row you hover lights a chart you can see")
    );

    tableC.textContent = "";
    tableC.appendChild(
      chip("Compact rows", function () {
        state.compact = !state.compact;
        applyView();
        touch();
      }, "Hide the per-item descriptions")
    );
    // An action, not a toggle: it is disabled when there is nothing to clear
    // rather than lit when there is, which would read as "sort is cleared".
    var clear = chip("Clear sort", function () {
      state.sort = null;
      applyView();
      touch();
    }, "Back to the ring order");
    clear.id = "pm-clear-sort";
    tableC.appendChild(clear);

    secC.textContent = "";
    secC.appendChild(chip("Expand all", function () {
      setAllCollapsed(false);
    }));
    secC.appendChild(chip("Collapse all", function () {
      setAllCollapsed(true);
    }));

    exportC.textContent = "";
    exportC.appendChild(chip("Copy as TSV", copyTsv, "Copy the visible rows to the clipboard"));
  }

  function updatePinChip() {
    if (!pinChip) return;
    if (!state.pinned) {
      pinChip.hidden = true;
      return;
    }
    pinChip.hidden = false;
    pinChip.firstChild.textContent = "Pinned: " + labelOf(state.pinned);
  }

  // --- copy ----------------------------------------------------------------
  function visibleRows() {
    var out = [];
    sections.forEach(function (sec) {
      out.push(sec.catRow);
      if (state.collapsed.has(sec.owner.key)) return;
      sortedItems(sec).forEach(function (it) {
        out.push(it.tr);
      });
    });
    footRows.forEach(function (f) {
      out.push(f.tr);
    });
    return out;
  }

  // Built from the DOM rather than the payload so the export is exactly what is
  // on screen: current sort order, and summary-only for a folded owner.
  function tsvText() {
    var head = [];
    var ths = headerRows[0].cells;
    for (var i = 0; i < ths.length; i++) head.push(ths[i].textContent.trim());
    var lines = [head.join("\t")];
    visibleRows().forEach(function (tr) {
      var cells = [];
      for (var j = 0; j < tr.cells.length; j++) {
        // The description lives in a <span> inside the name cell; the label is
        // the text before it. Taken by length rather than by cloning the cell,
        // which would cost a node copy per row.
        var c = tr.cells[j];
        var sub = c.querySelector(".pm-sub");
        var text = sub ? c.textContent.slice(0, c.textContent.length - sub.textContent.length) : c.textContent;
        cells.push(text.replace(/\s+/g, " ").trim());
      }
      lines.push(cells.join("\t"));
    });
    return lines.join("\n");
  }

  function copyTsv(e) {
    var text = tsvText();
    var btn = e && e.currentTarget;

    function done(ok) {
      if (!btn) return;
      var was = btn.textContent;
      btn.textContent = ok ? "Copied" : "Copy failed";
      btn.classList.add("on");
      setTimeout(function () {
        btn.textContent = was;
        btn.classList.remove("on");
      }, 1400);
    }

    // navigator.clipboard is undefined on file://, which is a supported way to
    // open this report, so the textarea path is a real fallback and not legacy.
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        done(true);
      }, function () {
        done(legacyCopy(text));
      });
    } else {
      done(legacyCopy(text));
    }
  }

  function legacyCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (err) {
      return false;
    }
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

  // What "Reserved" means, for a reader who knows Task Manager and not the
  // address space. How the owner-charged reserve is split out of it is left to
  // the data model (see the header) rather than spelled out on the page.
  function reservedNote() {
    return note([
      ["Reserved memory holds nothing."],
      " It is address space that has been spoken for and never backed with pages: invisible in " +
        "Task Manager, yet no other allocation can use those addresses. In a 32-bit process " +
        "address space, not physical memory, is what runs out."
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

  // --- view ----------------------------------------------------------------
  function applyView() {
    if (!host) return;

    host.classList.toggle("pm-sticky", state.sticky);
    host.classList.toggle("pm-compact", state.compact);

    // Row order and visibility.
    var nodes = [];
    sections.forEach(function (sec) {
      var folded = state.collapsed.has(sec.owner.key);
      if (sec.rehead) nodes.push(sec.rehead);
      nodes.push(sec.catRow);
      sec.catRow.classList.toggle("pm-folded", folded);
      var disc = sec.catRow.querySelector(".pm-disc");
      if (disc) {
        disc.setAttribute("aria-expanded", folded ? "false" : "true");
        disc.setAttribute("aria-label", (folded ? "Expand " : "Collapse ") + sec.owner.name);
      }
      sortedItems(sec).forEach(function (it) {
        it.tr.hidden = folded;
        nodes.push(it.tr);
      });
    });
    footRows.forEach(function (f) {
      nodes.push(f.tr);
    });
    // appendChild moves an existing node, so this re-orders in place.
    nodes.forEach(function (n) {
      tbodyEl.appendChild(n);
    });

    // Sort arrows on every header row, real and repeated.
    headerRows.forEach(function (tr) {
      for (var i = 1; i < tr.cells.length; i++) {
        var btn = tr.cells[i].querySelector(".pm-sortbtn");
        if (!btn) continue;
        var active = state.sort && state.sort.col === i;
        btn.classList.toggle("on", !!active);
        btn.querySelector(".pm-sortarrow").textContent = active
          ? state.sort.dir === "asc" ? "▲" : "▼"
          : "";
        tr.cells[i].setAttribute(
          "aria-sort",
          active ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none"
        );
      }
    });

    // Control chips reflect state.
    setChipState("pm-chart-controls", 0, state.sticky);
    setChipState("pm-table-controls", 0, state.compact);
    var clear = document.getElementById("pm-clear-sort");
    if (clear) clear.disabled = !state.sort;

    updatePinChip();
    restTrace();
  }

  function setChipState(hostId, index, on) {
    var h = document.getElementById(hostId);
    if (!h || !h.children[index]) return;
    h.children[index].classList.toggle("on", !!on);
  }

  function touch() {
    Explorer.Router.touch("process_memory");
  }

  // --- render --------------------------------------------------------------
  var built = false;

  function build() {
    if (built) return;
    host = document.getElementById("pm-body");
    if (!host) return;
    host.textContent = "";
    segs = [];
    donutSegs = {};
    rows = {};
    sections = [];
    footRows = [];
    headerRows = [];
    heatMax = 0;

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
    key.appendChild(el("span", null, "Hover to trace across both charts, click to pin"));

    // The pin chip: the only way back out of a pin without hunting for the row
    // you pinned, and a standing reminder that the highlight is held, not stuck.
    pinChip = el("span", "pm-pinchip");
    pinChip.appendChild(el("span", null, ""));
    var unpin = el("button", "pm-unpin", "✕");
    unpin.type = "button";
    unpin.title = "Unpin (Esc)";
    unpin.addEventListener("click", function () {
      setPinned(null);
    });
    pinChip.appendChild(unpin);
    pinChip.hidden = true;
    key.appendChild(pinChip);
    host.appendChild(key);

    var notes = el("div", "pm-notes");
    notes.appendChild(reservedNote());
    notes.appendChild(dllNote(pts[0], pts[1]));
    host.appendChild(notes);

    var bar = el("div", "pm-tablebar");
    bar.appendChild(el("span", "pm-heatcap", "Change"));
    var ramp = el("span", "pm-heatramp");
    ramp.style.background =
      "linear-gradient(to right, rgba(" + HEAT_GOOD + ",0.43), rgba(" + HEAT_GOOD + ",0.07)," +
      "rgba(" + HEAT_BAD + ",0.07), rgba(" + HEAT_BAD + ",0.43))";
    bar.appendChild(el("span", "pm-heatend", "better"));
    bar.appendChild(ramp);
    bar.appendChild(el("span", "pm-heatend", "worse"));
    // Without this the reversal looks like a bug on the one section where a
    // minus sign is the alarming one.
    bar.appendChild(
      el("span", "pm-heatnote", "Headroom is scored in reverse: losing free space is the bad direction")
    );
    bar.appendChild(el("span", "pm-heathint", "Click a column to sort within each owner"));
    host.appendChild(bar);

    var scroll = el("div", "pm-scroll");
    scroll.appendChild(table(pts));
    host.appendChild(scroll);

    tip = document.getElementById("pm-tip");
    built = true;
  }

  function render() {
    build();
    applyView();
  }

  // Esc clears a pin from anywhere, which is the expected way out of a held
  // highlight and saves hunting for the row that set it.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (Explorer.Router.currentKey() !== "process_memory") return;
    if (!state.pinned) return;
    setPinned(null);
  });

  // --- url -----------------------------------------------------------------
  function encode() {
    var p = {};
    Ser.put(p, "st", Ser.boolOut(state.sticky), "0");
    Ser.put(p, "cp", Ser.boolOut(state.compact), "0");
    if (state.sort) p.so = state.sort.col + (state.sort.dir === "asc" ? "a" : "d");
    Ser.put(p, "pin", state.pinned, null);
    Ser.putSet(p, "x", state.collapsed, [], OWNER_KEYS);
    return p;
  }

  function decode(p) {
    // Reset every serialized field first (router contract C2): `p` holds only
    // the keys the hash carried, so without this a sort would survive
    // navigating back to a bare #ProcessMemory.
    state.sticky = Ser.boolIn(p.st, false);
    state.compact = Ser.boolIn(p.cp, false);
    state.sort = null;
    var m = /^([1-5])([ad])$/.exec(String(p.so || ""));
    if (m) state.sort = { col: +m[1], dir: m[2] === "a" ? "asc" : "desc" };
    state.pinned = Ser.strIn(p.pin, ALL_KEYS, null);
    state.collapsed = Ser.setIn(p.x, OWNER_KEYS);
    buildControls(); // control DOM only; the router draws straight after (C3)
  }

  buildControls();
  render();

  // `tsv` is the export the Copy button writes, exposed so it can be checked
  // without a focused document (the clipboard API refuses one that is not).
  window.ProcessMemoryReport = { render: render, tsv: tsvText };
  Explorer.Router.register({
    key: "process_memory",
    slug: "ProcessMemory",
    render: render,
    encode: encode,
    decode: decode
  });
})();
