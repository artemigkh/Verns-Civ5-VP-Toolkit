/* Leaders report — the civ x leader-attribute matrix VP's AI is tuned with,
   as green-shaded heatmap tables of civs (rows) against attributes (columns).

   Static reference data straight out of the game database (see
   db_util/db_export.py:export_leader_attributes), not autoplay results: these
   are the inputs to AI behaviour, not a measurement of it.

   Layout inverts civdata.com's chart — civs are the rows and attributes the
   columns — so a row reads as one civ's whole profile. The attributes come from
   four different tables in the game DB and only compare meaningfully against
   their own siblings, so each is its own labelled block:

     Personality            15 tuning columns on Leaders
     Flavors                38 Leader_Flavors biases
     Major Civ Approaches   7 Leader_MajorCivApproachBiases
     City-State Approaches  5 Leader_MinorCivApproachBiases

   Columns VP switches off for every leader don't reach the payload at all (see
   render.py's DISABLED_BIAS_VALUE), so City-State Approaches arrives with 4.

   A fifth block carries the victory pursuits, the one leader attribute that is
   categorical rather than a bias value and so has nothing to shade.

   Blocks are grouped into cards (see CARDS): four share the profile table and
   Flavors takes a card of its own at the bottom. Sharing a single *table*
   rather than sitting in four adjacent ones is what lets a civ's row line up
   across every block and carry one civ label — as separate tables they each
   repeated the 43-civ name column, which spent ~450px of the pane on duplicate
   labels and left every block scrolling.

   Cells are shaded per column, hovering a row lights it up across every block,
   and clicking a column header cycles that card's row sort (descending ->
   ascending -> back to A-Z by civ), matching the Instant Yields report. Sorting
   is the report's only control, so it has no sidebar panel of its own. */
(function () {
  "use strict";

  var P = window.PAYLOAD.leaders;

  var TEXT = "#d7dde7";
  var TEXT_DIM = "#8b97a8";

  // Victory-pursuit label colors, reusing the Overview report's victory-type
  // palette so "Domination" means the same color across the app.
  var PURSUIT_COLORS = {
    Domination: "#e35d3b",
    Science: "#5aa9e6",
    Culture: "#c77dff",
    Diplomacy: "#f0a24e",
  };

  // The categorical block. Not a payload group — it comes from leader_info.csv
  // rather than the attribute matrix — but it behaves like one column-wise, so
  // it takes the same block treatment under the key "pursuits".
  var PURSUITS_KEY = "pursuits";
  var PURSUITS_NAME = "Victory Pursuits";
  var PURSUIT_COLUMNS = [
    {
      label: "Leader",
      kind: "text",
      pick: function (civ) {
        return leaderOf(civ);
      },
    },
    {
      label: "Primary",
      kind: "pursuit",
      pick: function (civ) {
        return (P.leaders[civ] || {}).primary || "";
      },
    },
    {
      label: "Secondary",
      kind: "pursuit",
      pick: function (civ) {
        return (P.leaders[civ] || {}).secondary || "";
      },
    },
  ];

  // Cards, in display order, each listing the blocks that share its table.
  // Blocks in one card share a civ column, a row order and row hover. Flavors
  // sits last: it is the one block wide enough to need a card to itself, and
  // the 38 columns read as an appendix to the profile above them.
  var CARDS = [
    {
      id: "profile",
      keys: [
        "major-civ-approaches",
        "city-state-approaches",
        "personality",
        PURSUITS_KEY,
      ],
    },
    { id: "flavors", keys: ["flavors"] },
  ];

  var byKey = {};
  P.groups.forEach(function (g) {
    byKey[g.key] = g;
  });

  // Any group the payload gained that CARDS doesn't place — a future VP adding
  // a fifth attribute table — gets its own card rather than silently vanishing.
  var placed = {};
  CARDS.forEach(function (card) {
    card.keys.forEach(function (key) {
      placed[key] = true;
    });
  });
  P.groups.forEach(function (g) {
    if (!placed[g.key]) CARDS.push({ id: g.key, keys: [g.key] });
  });

  // Card id -> sort state. One sort per card, shared by every block in it: the
  // blocks are columns of a single table, so they cannot disagree about row
  // order. `key` names a column as "<block>|<index>" so a sort survives
  // toggling other blocks on and off.
  var sorts = {};
  CARDS.forEach(function (card) {
    sorts[card.id] = { key: null, dir: null };
  });

  // -------------------------------------------------------------------------
  // Per-column statistics, computed once: the payload is fixed and every civ is
  // always a row, so a column's range never changes.
  // -------------------------------------------------------------------------
  var stats = {};
  P.groups.forEach(function (g) {
    stats[g.key] = g.attributes.map(function (_, i) {
      var min = Infinity;
      var max = -Infinity;
      var sum = 0;
      var n = 0;
      P.civs.forEach(function (civ) {
        var v = g.rows[civ][i];
        if (v === null || v === undefined) return;
        if (v < min) min = v;
        if (v > max) max = v;
        sum += v;
        n += 1;
      });
      return n
        ? { min: min, max: max, mean: sum / n }
        : { min: 0, max: 0, mean: 0 };
    });
  });

  // -------------------------------------------------------------------------
  // Shading — the same green ramp the Instant Yields and Policies Performance
  // tables use, but normalized over the column's own [min, max] rather than
  // against zero. Those tables shade yield magnitudes: right-skewed, starting
  // at a true zero, so sqrt(value / colMax) spends its contrast on the low end
  // where the rows crowd together. Bias values are the opposite shape — they
  // cluster in a narrow band well above zero (VP uses -1..12, and ~2/3 of all
  // values land in 5..8) — so measuring against zero would paint every cell the
  // same mid green.
  //
  // GAMMA then biases the ramp the other way for the same reason sqrt suits the
  // yield tables: with a linear ramp the crowded middle of a column lands at
  // half intensity and 43 x 38 mid-green cells drown out the outliers, which
  // are the thing worth seeing. Above 1 it darkens the pack and keeps the top of
  // each column bright.
  // -------------------------------------------------------------------------
  var GAMMA = 1.8;

  function intensity(value, st) {
    if (value === null || value === undefined) return null;
    if (st.max <= st.min) return 0; // every civ shares this value: nothing to rank
    return Math.pow((value - st.min) / (st.max - st.min), GAMMA);
  }

  function shade(t) {
    if (t === null || t <= 0) return "transparent";
    var lo = [16, 40, 28];
    var hi = [46, 170, 90];
    var r = Math.round(lo[0] + (hi[0] - lo[0]) * t);
    var g = Math.round(lo[1] + (hi[1] - lo[1]) * t);
    var b = Math.round(lo[2] + (hi[2] - lo[2]) * t);
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function fmtMean(v) {
    return (Math.round(v * 10) / 10).toFixed(1);
  }

  function leaderOf(civ) {
    var info = P.leaders[civ] || {};
    return info.leader || "";
  }

  // -------------------------------------------------------------------------
  // Column model
  //
  // A card's columns are one flat list across all of its blocks, which is what
  // lets the two header rows, the body and the sort all agree on the same
  // ordering and on where one block ends and the next begins.
  // -------------------------------------------------------------------------
  function colKey(col) {
    return col.block + "|" + col.idx;
  }

  function cardColumns(card) {
    var cols = [];
    card.keys.forEach(function (key) {
      if (key === PURSUITS_KEY) {
        PURSUIT_COLUMNS.forEach(function (pc, i) {
          cols.push({
            block: key,
            blockName: PURSUITS_NAME,
            idx: i,
            label: pc.label,
            kind: pc.kind,
            pick: pc.pick,
          });
        });
        return;
      }
      var group = byKey[key];
      if (!group) return;
      group.attributes.forEach(function (attr, i) {
        cols.push({
          block: key,
          blockName: group.name,
          idx: i,
          label: attr,
          kind: "value",
          group: group,
          stat: stats[key][i],
        });
      });
    });
    return cols;
  }

  // The columns at a block's edges, which carry the divider and the padding
  // either side of it. The first block needs no leading divider: the sticky civ
  // column's own right edge already closes it off.
  function startsBlock(cols, i) {
    return i > 0 && cols[i - 1].block !== cols[i].block;
  }

  function endsBlock(cols, i) {
    return i < cols.length - 1 && cols[i + 1].block !== cols[i].block;
  }

  function edgeClasses(cols, i, el) {
    if (startsBlock(cols, i)) el.classList.add("ldr-block-start");
    if (endsBlock(cols, i)) el.classList.add("ldr-block-end");
  }

  // The blocks as [start, span] runs over the flat column list, which the two
  // header rows and the body all walk so they agree on the boundaries.
  function blockRuns(cols) {
    var runs = [];
    var i = 0;
    while (i < cols.length) {
      var span = 1;
      while (i + span < cols.length && cols[i + span].block === cols[i].block) {
        span += 1;
      }
      runs.push({ start: i, span: span, name: cols[i].blockName });
      i += span;
    }
    return runs;
  }

  function cellValue(col, civ) {
    if (col.kind === "value") {
      var v = col.group.rows[civ][col.idx];
      return v === null || v === undefined ? null : v;
    }
    return col.pick(civ);
  }

  // -------------------------------------------------------------------------
  // Sorting
  // -------------------------------------------------------------------------
  function compare(col, a, b, dir) {
    var va = cellValue(col, a);
    var vb = cellValue(col, b);
    if (col.kind === "value") {
      if (va === null) va = -Infinity;
      if (vb === null) vb = -Infinity;
      if (va !== vb) return dir * (va - vb);
    } else {
      // Blanks sort last in both directions: a leader declaring no pursuit is
      // an absent value, not one that ranks below "Culture".
      var emptyA = !va;
      var emptyB = !vb;
      if (emptyA !== emptyB) return emptyA ? 1 : -1;
      var c = String(va).localeCompare(String(vb));
      if (c !== 0) return dir * c;
    }
    return a.localeCompare(b); // stable, readable tiebreak
  }

  function sortedCivs(card, cols) {
    var s = sorts[card.id];
    var civs = P.civs.slice();
    if (!s.key) return civs; // payload order is already A-Z by civ
    var col = null;
    for (var i = 0; i < cols.length; i++) {
      if (colKey(cols[i]) === s.key) col = cols[i];
    }
    if (!col) return civs; // sorted column no longer in this card
    var dir = s.dir === "asc" ? 1 : -1;
    civs.sort(function (a, b) {
      return compare(col, a, b, dir);
    });
    return civs;
  }

  // Cycle a column's sort: desc -> asc -> default (A-Z by civ).
  function cycleSort(card, key) {
    var s = sorts[card.id];
    if (s.key !== key) {
      s.key = key;
      s.dir = "desc";
    } else if (s.dir === "desc") {
      s.dir = "asc";
    } else {
      s.key = null;
      s.dir = null;
    }
    render();
  }

  // -------------------------------------------------------------------------
  // Rotated-header geometry
  //
  // A CSS transform doesn't change an element's layout box, so the diagonal
  // labels contribute nothing to the header's size and would otherwise spill
  // out of the card. Both dimensions they need are measured once the table is
  // in the DOM.
  //
  // Rotating a w x h box -45 degrees about its bottom-left corner puts its
  // corners at (0,0), (-h, -h), (w, -w) and (w-h, -(w+h)), all scaled by
  // 1/sqrt(2) — so relative to the anchor the box
  //
  //   rises   (w + h)/sqrt(2)   — h matters: the text's line box tips upward
  //                               too, and leaving it out clipped the longest
  //                               labels against the block headings.
  //   reaches w/sqrt(2) right   — what the trailing columns overhang by.
  //   reaches h/sqrt(2) left    — which is why the labels are inset from their
  //                               cell's left edge (see LABEL_INSET); without
  //                               it the first label slid under the sticky civ
  //                               column, which paints above it.
  // -------------------------------------------------------------------------
  var ARROW_BAND = 15; // upright sort arrow's strip along the bottom of the header
  // Fallback for .ldr-attr-label's left offset, used only if the computed value
  // can't be read. The real inset comes from CSS and varies: a column opening a
  // block carries extra left padding for the block gap, and its label is inset
  // to match. Whatever the value, it must stay >= h/sqrt(2) (~8px at the
  // header's 10px/1.1 type) or the label's tail crosses its cell's left edge.
  var LABEL_INSET = 9;

  function sizeRotatedHeaders(table) {
    // The column row, not the block-heading row above it.
    var colRow = table.querySelectorAll("thead tr")[1];
    if (!colRow) return;
    var cells = colRow.querySelectorAll("th");
    if (!cells.length) return;
    var tableRight = table.getBoundingClientRect().right;

    var rise = 0;
    var overhang = 0;
    for (var i = 0; i < cells.length; i++) {
      var label = cells[i].querySelector(".ldr-attr-label");
      if (!label) continue;
      // Layout size of the un-rotated content; the transform can't skew it.
      var w = label.scrollWidth;
      var h = label.offsetHeight;
      var up = (w + h) * Math.SQRT1_2;
      if (up > rise) rise = up;
      var inset = parseFloat(window.getComputedStyle(label).left);
      if (isNaN(inset)) inset = LABEL_INSET;
      var right =
        cells[i].getBoundingClientRect().left + inset + w * Math.SQRT1_2;
      if (right - tableRight > overhang) overhang = right - tableRight;
    }
    if (!rise) return;

    var height = Math.ceil(rise) + ARROW_BAND + "px";
    for (var j = 0; j < cells.length; j++) {
      cells[j].style.height = height;
    }
    // Room for the trailing labels to lean into, reserved as padding on the
    // scroller rather than margin on the table. The table is width: 100%, so
    // padding shrinks it to fit and the labels overhang into the gap; a margin
    // would instead push past the scroller's edge and raise a scrollbar over
    // whitespace. Only the labels near the end can overhang, and each column
    // further from the end absorbs one column's width of its own reach, so
    // this is a per-column max rather than the longest label's reach.
    var scroller = table.parentNode;
    if (scroller) scroller.style.paddingRight = Math.ceil(overhang) + "px";
  }

  // -------------------------------------------------------------------------
  // Tile width
  //
  // Every value column gets the same tile width, computed so the table exactly
  // spans its card. Left to CSS the widths come out lopsided: auto table layout
  // hands spare width out in proportion to each column's content, and a block
  // heading spanning few columns (City-State Approaches over 4) drags those
  // columns wide while a short heading over many (Personality over 15) leaves
  // them narrow — tiles ranged from 17px to 42px in the same row.
  //
  // The width is derived from what the row spends on everything that isn't a
  // tile, rather than from the table's own width: the table is width: 100%, so
  // it always measures as full and a "how much is spare" reading always came
  // back as zero. Value columns are content-box, so the property is the tile
  // width itself and each column's padding and border count as fixed.
  // -------------------------------------------------------------------------
  var MIN_TILE_W = 20; // floor when the window is too narrow to share anything out

  function fitTiles(table) {
    var scroller = table.parentNode;
    var row = table.querySelector("tbody tr");
    if (!scroller || !row) return;

    var fixed = 0;
    var count = 0;
    Array.prototype.forEach.call(row.cells, function (td) {
      var cs = window.getComputedStyle(td);
      if (td.classList.contains("ldr-value")) {
        count += 1;
        // Everything in this column that the tile doesn't occupy: its gutter,
        // plus the seam padding and divider on a block's edge columns.
        fixed +=
          parseFloat(cs.paddingLeft) +
          parseFloat(cs.paddingRight) +
          parseFloat(cs.borderLeftWidth) +
          parseFloat(cs.borderRightWidth);
      } else {
        // Civ label and the categorical columns, all at their content width.
        fixed += td.getBoundingClientRect().width;
      }
    });
    if (!count) return;

    var w = (scroller.clientWidth - fixed) / count;
    table.style.setProperty(
      "--ldr-tile-w",
      Math.max(MIN_TILE_W, w).toFixed(2) + "px"
    );
  }

  // -------------------------------------------------------------------------
  // Header
  // -------------------------------------------------------------------------
  function sortArrow(dir, inline) {
    var arrow = document.createElement("span");
    arrow.className = "ldr-sort-arrow" + (inline ? " ldr-sort-inline" : "");
    if (dir) {
      arrow.textContent = dir === "asc" ? "▲" : "▼";
    } else {
      arrow.className += " ldr-sort-idle";
      arrow.textContent = "⇅";
    }
    return arrow;
  }

  function buildHeader(card, cols) {
    var s = sorts[card.id];
    var thead = document.createElement("thead");

    // Row 1 — one spanning heading per block. The block names live here, which
    // is why the cards carry no separate titles.
    var blockTr = document.createElement("tr");
    var corner = document.createElement("th");
    corner.className = "ldr-corner";
    corner.rowSpan = 2;
    corner.textContent = "Civilization";
    blockTr.appendChild(corner);

    var runs = blockRuns(cols);
    runs.forEach(function (run, ri) {
      var bth = document.createElement("th");
      bth.className = "ldr-block-head";
      if (ri > 0) bth.classList.add("ldr-block-start");
      if (ri < runs.length - 1) bth.classList.add("ldr-block-end");
      bth.colSpan = run.span;
      bth.textContent = run.name;
      blockTr.appendChild(bth);
    });
    thead.appendChild(blockTr);

    // Row 2 — the sortable columns.
    var colTr = document.createElement("tr");
    cols.forEach(function (col, idx) {
      var key = colKey(col);
      var dir = s.key === key ? s.dir : null;
      var th = document.createElement("th");
      th.className = col.kind === "value" ? "ldr-attr-col" : "ldr-text-col";
      if (dir) th.classList.add("ldr-sorted");
      edgeClasses(cols, idx, th);

      if (col.kind === "value") {
        // Labels are rotated 45 degrees rather than stood on end: at the ~22px
        // column pitch a diagonal label clears its neighbour, and it stays far
        // easier to read than vertical text. Rotation is also what lets a
        // column shrink to its digits — laid out horizontally, 38 flavor labels
        // would make that table several screens wide.
        var label = document.createElement("div");
        label.className = "ldr-attr-label";
        label.textContent = col.label;
        th.appendChild(label);
        // The arrow sits outside the rotated label so it stays upright: a
        // triangle turned 45 degrees no longer reads as "up" or "down".
        th.appendChild(sortArrow(dir, false));
      } else {
        // Text columns are wide enough for a horizontal label and inline arrow.
        var text = document.createElement("span");
        text.className = "ldr-text-label";
        text.textContent = col.label;
        th.appendChild(text);
        th.appendChild(sortArrow(dir, true));
      }

      th.addEventListener("click", function () {
        cycleSort(card, key);
      });
      colTr.appendChild(th);
    });
    thead.appendChild(colTr);

    return thead;
  }

  // -------------------------------------------------------------------------
  // Body
  // -------------------------------------------------------------------------
  function valueCell(col, civ) {
    var v = cellValue(col, civ);
    var t = intensity(v, col.stat);
    var td = document.createElement("td");
    td.className = "ldr-value";
    // Shading goes straight on the cell, as in the Policies Performance
    // "Branch Opens by Civilization" table: a cell's background covers its
    // padding, so neighbours sit flush and the block reads as one grid rather
    // than a field of separate tiles.
    td.textContent = v === null ? "" : String(v);
    td.style.background = shade(t);
    // Dim the faintly-shaded end of the ramp so it reads as "low" rather than
    // as an unfilled cell, matching the other heatmap tables.
    td.style.color = t !== null && t > 0.06 ? TEXT : TEXT_DIM;
    td.title =
      civ +
      " (" +
      leaderOf(civ) +
      ")\n" +
      col.blockName +
      " — " +
      col.label +
      ": " +
      (v === null ? "n/a" : v) +
      "\nAll civs: " +
      col.stat.min +
      "–" +
      col.stat.max +
      ", mean " +
      fmtMean(col.stat.mean);
    return td;
  }

  function textCell(col, civ) {
    var td = document.createElement("td");
    td.className = "ldr-leader-name";
    td.textContent = col.pick(civ);
    return td;
  }

  function pursuitCell(col, civ) {
    var td = document.createElement("td");
    td.className = "ldr-pursuit";
    var value = col.pick(civ);
    if (!value) {
      td.textContent = "—";
      td.style.color = TEXT_DIM;
    } else {
      td.textContent = value;
      td.style.color = PURSUIT_COLORS[value] || TEXT;
    }
    return td;
  }

  function buildBody(card, cols) {
    var tbody = document.createElement("tbody");

    sortedCivs(card, cols).forEach(function (civ) {
      var tr = document.createElement("tr");
      // The one civ label for this row, shared by every block in the card and
      // sticky so it stays put while the table scrolls sideways.
      var name = document.createElement("td");
      name.className = "ldr-civ-name";
      name.textContent = civ;
      name.title = leaderOf(civ);
      tr.appendChild(name);

      cols.forEach(function (col, idx) {
        var td =
          col.kind === "value"
            ? valueCell(col, civ)
            : col.kind === "text"
            ? textCell(col, civ)
            : pursuitCell(col, civ);
        edgeClasses(cols, idx, td);
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
    });

    return tbody;
  }

  // -------------------------------------------------------------------------
  // Card
  // -------------------------------------------------------------------------
  function buildCard(card, cols, host) {
    var el = document.createElement("div");
    el.className = "ldr-card";

    var scroller = document.createElement("div");
    scroller.className = "ldr-scroll";
    var table = document.createElement("table");
    table.className = "ldr-table";
    table.appendChild(buildHeader(card, cols));
    table.appendChild(buildBody(card, cols));
    scroller.appendChild(table);
    el.appendChild(scroller);

    if (card.keys.indexOf(PURSUITS_KEY) !== -1) {
      var note = document.createElement("p");
      note.className = "ldr-card-note";
      note.textContent =
        "Victory pursuits are the victory conditions a leader is steered " +
        "toward. Unlike the bias values they are categorical, and a leader " +
        "may declare neither.";
      el.appendChild(note);
    }

    host.appendChild(el);
    // Both passes measure laid-out geometry, so they follow the append. Header
    // sizing goes first: it reserves the scroller padding that fitTiles then
    // measures the available width against.
    sizeRotatedHeaders(table);
    // Twice: the first pass measures the content columns while the table may
    // still be stretching them to fill, and applying the fitted width settles
    // that, so the second pass reads the widths that actually hold.
    fitTiles(table);
    fitTiles(table);
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  function render() {
    var host = document.getElementById("ldr-tables");
    if (!host) return;
    host.textContent = "";

    CARDS.forEach(function (card) {
      var cols = cardColumns(card);
      if (cols.length) buildCard(card, cols, host);
    });
  }

  render();

  window.LeadersReport = { render: render };
})();
