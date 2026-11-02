/* Dataset loader and switcher. Runs after the bundle is defined (as
   window.__explorerMain) and before any of it executes: every report module
   reads window.PAYLOAD as it loads, so PAYLOAD has to hold the dataset the URL
   names first.

   The dataset rides in the hash like every other piece of shareable state --
   #ReligionYields?ds=5_4_7&y=Gold -- and an absent ds means the default one.
   The default is inlined (#payload-default); any other is a sidecar
   datasets/<id>.js loaded by <script src>, which works over file:// where
   fetch() does not.

   Every payload that arrives is kept in window.EXPLORER_PAYLOADS[id] for the
   life of the tab, so a dataset is fetched and parsed at most once. Switching
   datasets (Explorer.Datasets.activate, called by the router on a hashchange
   whose ds differs from the loaded one) does not reload the page: the modules
   derive their defaults, lookup tables and control DOM from PAYLOAD as they
   load, so rather than teaching thirteen of them to re-read it, the switch
   tears the page body down and runs the bundle again against the cached
   payload. Module state lives in the hash, which the new router re-applies,
   exactly as a reload would -- minus the network and the parse.

   Teardown has to undo everything a bundle run leaves outside the DOM it owns:
   the window/document listeners the modules add at load (resize debounces, the
   sidebar drag handlers, the router's hashchange, Process Memory's Escape key)
   are recorded by wrapping addEventListener for the duration of the run and
   removed; Plotly plots are purged; the body's non-script children are replaced
   with fresh clones of the template. Sidebar collapse state and widths carry
   over. */
(function () {
  "use strict";
  var M = window.EXPLORER_DATASETS;
  var PAYLOADS = (window.EXPLORER_PAYLOADS = window.EXPLORER_PAYLOADS || {});
  var FAILED = {}; // id -> true when its sidecar could not be loaded
  var PENDING = {}; // id -> callbacks waiting on its sidecar
  var ACTIVE = null; // dataset the running bundle shows
  var LISTENERS = []; // [target, type, fn, opts] added during the last bundle run

  function hasOwn(o, k) {
    return Object.prototype.hasOwnProperty.call(o, k);
  }

  function labelOf(id) {
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) return M.list[i].label;
    return null;
  }

  // Just enough of router.js's parseHash to find the raw ds value ("" when
  // absent); the router re-parses the whole hash once the bundle runs.
  function rawHashDataset() {
    var h = location.hash;
    var q = h.indexOf("?");
    if (q < 0) return "";
    var pairs = h.slice(q + 1).split("&");
    for (var i = 0; i < pairs.length; i++) {
      var eq = pairs[i].indexOf("=");
      if (eq > 0 && pairs[i].slice(0, eq) === "ds") {
        try {
          return decodeURIComponent(pairs[i].slice(eq + 1));
        } catch (e) {
          return "";
        }
      }
    }
    return "";
  }

  // The dataset the hash names: an absent or unknown ds is the default.
  function hashDataset() {
    var v = rawHashDataset();
    return v && labelOf(v) !== null ? v : M["default"];
  }

  // The template's body, as it was before any bundle ran: what a switch
  // restores. Scripts stay where they are (re-inserting them would re-run them).
  var PRISTINE = [];
  var kids = document.body.children;
  for (var i = 0; i < kids.length; i++) {
    if (kids[i].tagName !== "SCRIPT") PRISTINE.push(kids[i].cloneNode(true));
  }

  // --- payloads -------------------------------------------------------------

  function defaultPayload() {
    var id = M["default"];
    if (!hasOwn(PAYLOADS, id)) {
      PAYLOADS[id] = JSON.parse(document.getElementById("payload-default").textContent);
    }
    return PAYLOADS[id];
  }

  // Have dataset `id`'s payload in the cache, then call done(ok). Synchronous
  // when it is already there (or already known to be unloadable); otherwise the
  // sidecar loads once and every waiter runs.
  function load(id, done) {
    if (id === M["default"]) {
      defaultPayload();
      return done(true);
    }
    if (hasOwn(PAYLOADS, id)) return done(true);
    if (FAILED[id]) return done(false);
    if (PENDING[id]) return PENDING[id].push(done);
    PENDING[id] = [done];
    function flush(ok) {
      var waiters = PENDING[id] || [];
      delete PENDING[id];
      waiters.forEach(function (fn) {
        fn(ok);
      });
    }
    var script = document.createElement("script");
    script.src = M.dir + "/" + encodeURIComponent(id) + ".js";
    script.onload = function () {
      // The sidecar assigns window.PAYLOAD; capture it and put the running
      // dataset's payload back, since the page may be showing another one.
      var ok = !!(window.PAYLOAD && window.PAYLOAD.dataset === id);
      if (ok) PAYLOADS[id] = window.PAYLOAD;
      else FAILED[id] = true;
      if (ACTIVE !== null) window.PAYLOAD = PAYLOADS[ACTIVE];
      flush(ok);
    };
    script.onerror = function () {
      FAILED[id] = true;
      flush(false);
    };
    document.head.appendChild(script);
  }

  // --- running the bundle ---------------------------------------------------

  function recordListeners(target) {
    var own = Object.prototype.hasOwnProperty.call(target, "addEventListener");
    var orig = target.addEventListener;
    target.addEventListener = function (type, fn, opts) {
      LISTENERS.push([target, type, fn, opts]);
      return orig.call(target, type, fn, opts);
    };
    return function () {
      if (own) target.addEventListener = orig;
      else delete target.addEventListener; // back to EventTarget.prototype's
    };
  }

  function run(id, note) {
    ACTIVE = id;
    window.PAYLOAD = PAYLOADS[id];
    // switcher.js shows this under the Dataset dropdown; the router then drops
    // the ds the URL could not honour, so the URL matches what is shown.
    window.EXPLORER_DATASET_NOTE = note || null;
    LISTENERS = [];
    var restoreW = recordListeners(window);
    var restoreD = recordListeners(document);
    try {
      window.__explorerMain();
    } finally {
      restoreW();
      restoreD();
    }
  }

  function teardown() {
    LISTENERS.forEach(function (l) {
      l[0].removeEventListener(l[1], l[2], l[3]);
    });
    LISTENERS = [];
    if (window.Plotly) {
      var plots = document.querySelectorAll(".js-plotly-plot");
      for (var i = 0; i < plots.length; i++) {
        try {
          window.Plotly.purge(plots[i]);
        } catch (e) {
          /* a half-built plot; nothing to free */
        }
      }
    }
    // Carry the chrome's state over: which sidebars are collapsed, how wide.
    var app = document.getElementById("app");
    var collapsed = [];
    var widths = {};
    if (app) {
      ["collapsed", "collapsed-right"].forEach(function (c) {
        if (app.classList.contains(c)) collapsed.push(c);
      });
      ["sidebar", "sidebar-right"].forEach(function (sid) {
        var el = document.getElementById(sid);
        if (el && el.style.width) widths[sid] = el.style.width;
      });
    }
    var body = document.body;
    var old = body.children;
    for (var j = old.length - 1; j >= 0; j--) {
      if (old[j].tagName !== "SCRIPT") body.removeChild(old[j]);
    }
    var first = body.firstChild; // the scripts sit at the end of the body
    PRISTINE.forEach(function (node) {
      body.insertBefore(node.cloneNode(true), first);
    });
    body.style.cursor = "";
    body.style.userSelect = "";
    var fresh = document.getElementById("app");
    if (fresh) {
      collapsed.forEach(function (c) {
        fresh.classList.add(c);
      });
      Object.keys(widths).forEach(function (sid) {
        var el = document.getElementById(sid);
        if (el) el.style.width = widths[sid];
      });
    }
  }

  // --- public ---------------------------------------------------------------

  window.Explorer = window.Explorer || {};
  window.Explorer.Datasets = {
    // The dataset the running bundle shows.
    active: function () {
      return ACTIVE;
    },
    loaded: function (id) {
      return hasOwn(PAYLOADS, id);
    },
    // A cached payload, or null. comparison.js reads a loaded dataset's civs
    // slice from here rather than fetching its .civs.js sidecar.
    payload: function (id) {
      return hasOwn(PAYLOADS, id) ? PAYLOADS[id] : null;
    },
    // Show dataset `id` in place of the current one, without reloading. The
    // bundle re-runs once the payload is here; its router then applies
    // whatever the hash says at that moment. done(false) when the sidecar
    // could not load (the page is left as it was); done(true) is never called,
    // because the caller's bundle no longer exists by then. A hash that moves
    // on to another dataset while the sidecar loads wins: the stale load is
    // cached and otherwise ignored.
    activate: function (id, done) {
      if (labelOf(id) === null || id === ACTIVE) return;
      load(id, function (ok) {
        if (hashDataset() !== id) return;
        if (!ok) return done && done(false);
        teardown();
        try {
          run(id);
        } catch (e) {
          // A bundle that failed half-way leaves a broken page; a reload under
          // the same hash is the one recovery that cannot make it worse.
          if (window.console) console.error("[boot] dataset switch failed, reloading", e);
          location.reload();
        }
      });
    }
  };

  // --- first run ------------------------------------------------------------

  function useDefault(note) {
    defaultPayload();
    run(M["default"], note);
  }

  var raw = rawHashDataset();
  if (raw && labelOf(raw) === null) {
    return useDefault('No dataset "' + raw + '" in this build, showing the default.');
  }
  var want = hashDataset();
  if (want === M["default"]) return useDefault();
  load(want, function (ok) {
    if (ok) run(want);
    else useDefault('Could not load the "' + labelOf(want) + '" dataset, showing the default.');
  });
})();
