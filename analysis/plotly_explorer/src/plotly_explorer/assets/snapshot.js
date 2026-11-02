/* Report snapshot: the camera buttons save everything outside the control
   panels -- #main-inner, at its full scrolled height -- as a PNG download.

   No screenshot API reaches content scrolled out of view, so the pane is
   redrawn instead: a copy of #main-inner goes into an SVG <foreignObject>
   along with the page's own stylesheets, and the browser rasterizes that SVG
   onto a canvas. Plotly's charts are already SVG in the DOM, so they come
   along as vectors and stay sharp at the 2x the image is drawn at.

   The copy sits under a stand-in #app carrying the live #app's classes,
   because the report-hiding rules (#app.show-<key> .report-<key>) are what
   decide which report's pane is visible. */
(function () {
  "use strict";

  var PAD_X = 22; // #main's own padding, uncollapsed
  var PAD_Y = 18;
  var MIN_SCALE = 2;
  // Stay under every browser's canvas ceiling (Chrome and Firefox cap each side
  // at 32767 px; Firefox caps the area lower than Chrome does).
  var MAX_SIDE = 32000;
  var MAX_AREA = 120e6;

  function pageCss() {
    var out = [];
    var sheets = document.styleSheets;
    for (var i = 0; i < sheets.length; i++) {
      var rules;
      try {
        rules = sheets[i].cssRules;
      } catch (e) {
        continue; // a cross-origin sheet; the explorer has none
      }
      for (var j = 0; j < rules.length; j++) out.push(rules[j].cssText);
    }
    return out.join("\n");
  }

  // The content's own height: #main-inner's min-height:100% (which centres a
  // short report in the viewport) would otherwise pad the image with the
  // empty space around it.
  function contentHeight(inner) {
    var prev = inner.style.minHeight;
    inner.style.minHeight = "0px";
    var h = inner.getBoundingClientRect().height;
    inner.style.minHeight = prev;
    return h;
  }

  function buildSvg(app, inner, w, h) {
    var body = getComputedStyle(document.body);
    var copy = inner.cloneNode(true);
    copy.style.minHeight = "0px";
    copy.style.width = w + "px";
    // Hover chrome: a Plotly hover label left behind by the pointer.
    var hover = copy.querySelectorAll(".hoverlayer, .modebar-container");
    for (var i = 0; i < hover.length; i++) {
      while (hover[i].firstChild) hover[i].removeChild(hover[i].firstChild);
    }

    var frame = document.createElement("div");
    frame.id = "app";
    frame.className = app.className;
    frame.setAttribute(
      "style",
      "display:block;position:relative;overflow:visible;height:auto;" +
        "width:" + (w + 2 * PAD_X) + "px;" +
        "background:" + body.backgroundColor + ";color:" + body.color + ";" +
        "font-family:" + body.fontFamily + ";font-size:" + body.fontSize + ";"
    );
    var style = document.createElement("style");
    // A table wider than its card keeps its on-screen cut, minus the
    // scrollbar, which means nothing in a still image.
    style.textContent =
      pageCss() +
      "\n#main-inner * { scrollbar-width: none; }" +
      "\n#main-inner *::-webkit-scrollbar { display: none; }";
    var main = document.createElement("main");
    main.id = "main";
    main.setAttribute(
      "style",
      "display:block;height:auto;overflow:visible;padding:" + PAD_Y + "px " + PAD_X + "px;"
    );
    main.appendChild(copy);
    frame.appendChild(style);
    frame.appendChild(main);

    var W = Math.ceil(w + 2 * PAD_X);
    var H = Math.ceil(h + 2 * PAD_Y);
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '">' +
      '<foreignObject x="0" y="0" width="100%" height="100%">' +
      new XMLSerializer().serializeToString(frame) +
      "</foreignObject></svg>";
    return { svg: svg, width: W, height: H, background: body.backgroundColor };
  }

  function pickScale(W, H) {
    var s = Math.max(MIN_SCALE, window.devicePixelRatio || 1);
    s = Math.min(s, MAX_SIDE / W, MAX_SIDE / H, Math.sqrt(MAX_AREA / (W * H)));
    return s;
  }

  function stamp() {
    var d = new Date();
    function two(n) {
      return (n < 10 ? "0" : "") + n;
    }
    return (
      d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate()) +
      "_" + two(d.getHours()) + two(d.getMinutes()) + two(d.getSeconds())
    );
  }

  // vp-explorer_<dataset>_<report>_<time>.png; the Comparison report names
  // its two datasets instead of the page's.
  function fileName() {
    var report = document.getElementById("report-select");
    var key = report ? report.value : "report";
    var ds = "";
    if (key === "comparison") {
      var a = document.getElementById("cmp-ds-a");
      var b = document.getElementById("cmp-ds-b");
      if (a && b) ds = a.value + "_vs_" + b.value;
    } else if (window.Explorer && window.Explorer.Router) {
      ds = window.Explorer.Router.datasets().current;
    }
    var name = ["vp-explorer", ds, key, stamp()].filter(Boolean).join("_");
    return name.replace(/[^\w.-]+/g, "-") + ".png";
  }

  function download(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 10000);
  }

  var busy = false;

  function setBusy(on) {
    busy = on;
    var btns = document.querySelectorAll(".snapshot-btn");
    for (var i = 0; i < btns.length; i++) btns[i].disabled = on;
    document.body.style.cursor = on ? "progress" : "";
  }

  function fail(err) {
    setBusy(false);
    if (window.console) console.error("[snapshot]", err);
    alert("Could not create the image" + (err && err.message ? ": " + err.message : "."));
  }

  function snapshot() {
    if (busy) return;
    var app = document.getElementById("app");
    var inner = document.getElementById("main-inner");
    if (!app || !inner) return;
    setBusy(true);
    var name = fileName();
    var shot;
    try {
      shot = buildSvg(app, inner, inner.getBoundingClientRect().width, contentHeight(inner));
    } catch (e) {
      fail(e);
      return;
    }
    var img = new Image();
    img.onerror = function () {
      fail(new Error("the browser could not draw the page"));
    };
    img.onload = function () {
      try {
        var s = pickScale(shot.width, shot.height);
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(shot.width * s);
        canvas.height = Math.round(shot.height * s);
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = shot.background;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (blob) {
          if (!blob) {
            fail(new Error("the image is too large to encode"));
            return;
          }
          download(blob, name);
          setBusy(false);
        }, "image/png");
      } catch (e) {
        fail(e);
      }
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(shot.svg);
  }

  var btns = document.querySelectorAll(".snapshot-btn");
  for (var i = 0; i < btns.length; i++) btns[i].addEventListener("click", snapshot);
})();
