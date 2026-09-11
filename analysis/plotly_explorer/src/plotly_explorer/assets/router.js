/* =============================================================================
 * Hash router + report registry.
 *
 * Loaded FIRST in the bundle: every report module calls Explorer.Router.register()
 * at its IIFE tail, and switcher.js (loaded LAST) calls Explorer.Router.start()
 * once they all have.
 *
 * The explorer ships as one self-contained HTML file served from GitHub Pages --
 * a static host with no rewrite support -- and is also opened straight off disk
 * over file://. That rules out path routing, so all shareable state lives in
 * location.hash:
 *
 *     #BuildingYields?y=Gold&m=total&de=Ancient,Classical&n=20
 *
 * ---------------------------------------------------------------------------
 * The registration contract. Four clauses; the middle two are the ones that
 * break quietly if you get them wrong.
 *
 *   C1. encode() returns ONLY non-default params. The router knows nothing
 *       about any module's defaults -- default-omission lives entirely in
 *       encode(), which is what keeps the URLs short. Values must be strings.
 *
 *   C2. decode(params) must RESET EVERY SERIALIZED FIELD TO ITS DEFAULT before
 *       overlaying params, because params holds only the keys present in the
 *       hash. Without the reset, navigating back from #X?y=Gold to #X leaves
 *       y=Gold in place. Easiest clause to get wrong, hardest to notice.
 *
 *   C3. decode() mutates state and rebuilds CONTROL DOM ONLY -- it must not
 *       draw. The router calls refresh() (or render()) immediately afterwards.
 *
 *   C4. encode(decode(h)) === h for every h that encode() can produce. A module
 *       that violates this would make the router ping-pong; touch() contains a
 *       loop breaker, but the fixpoint self-test is what actually catches it.
 * ========================================================================== */
(function () {
  "use strict";

  window.Explorer = window.Explorer || {};

  var DEFAULT_KEY = (window.PAYLOAD && window.PAYLOAD.defaultReport) || "civs";
  var WRITE_DELAY = 250; // the topN <input type=range> fires on every drag step

  var ORDER = []; // keys, registration order
  var BY_KEY = {};
  var BY_SLUG = {}; // lowercased slug -> key, so hand-typed links work

  var started = false;
  var currentKey = DEFAULT_KEY;

  // --- re-entrancy ---------------------------------------------------------
  // applying : true while decode() runs; a touch() during it is dropped.
  // echoing  : true while the router's own post-decode draw runs. Touches from
  //            that draw are dropped too -- applyHash canonicalizes the URL
  //            itself once the draw is done, which is both simpler and more
  //            correct than letting the draw author it (see applyHash).
  // expected : hashes we wrote and have not yet heard back about, so our own
  //            hashchange events do not re-enter decode. A string compare, not
  //            a timer -- ordering between the timer task source and the one
  //            that queues hashchange is implementation-defined.
  var applying = false;
  var echoing = false;
  var expected = [];
  var writeTimer = null;

  // --- hash <-> string -----------------------------------------------------

  function curHash() {
    var h = location.hash;
    return h === "#" ? "" : h; // a bare trailing '#' is "no hash"
  }

  function base() {
    var href = location.href;
    var i = href.indexOf("#");
    return i < 0 ? href : href.slice(0, i);
  }

  // Percent-encode, but leave ',' '|' and ':' raw: all three are legal in a
  // fragment, they are our own structural separators, and decodeURIComponent
  // passes them through unchanged. Keeps `de=Ancient,Classical` readable.
  function encVal(s) {
    return encodeURIComponent(String(s))
      .replace(/%2C/g, ",")
      .replace(/%7C/g, "|")
      .replace(/%3A/g, ":");
  }

  function decVal(s) {
    try {
      return decodeURIComponent(String(s));
    } catch (e) {
      return String(s);
    }
  }

  function parseQuery(qs) {
    var out = {};
    if (!qs) return out;
    qs.split("&").forEach(function (pair) {
      if (!pair) return;
      var i = pair.indexOf("=");
      var k = i < 0 ? pair : pair.slice(0, i);
      var v = i < 0 ? "" : pair.slice(i + 1);
      if (!k) return;
      out[decVal(k)] = decVal(v);
    });
    return out;
  }

  function parseHash(h) {
    h = String(h || "");
    if (h.charAt(0) === "#") h = h.slice(1);
    if (!h) return { key: DEFAULT_KEY, params: {} };
    var q = h.indexOf("?");
    var slug = q < 0 ? h : h.slice(0, q);
    var key = BY_SLUG[decVal(slug).toLowerCase()];
    // Unknown slug (renamed report, typo, stale bookmark): fall back to the
    // default report rather than showing nothing. The params go with it -- they
    // belonged to a report we cannot identify.
    if (!key) return { key: DEFAULT_KEY, params: {} };
    return { key: key, params: parseQuery(q < 0 ? "" : h.slice(q + 1)) };
  }

  // Param order is the insertion order of encode()'s object, which every engine
  // preserves for string keys. That makes the formatted string a stable function
  // of state -- required, because "did the hash change?" is a string compare and
  // two users in the same state must produce the same URL.
  function formatHash(key, params) {
    var reg = BY_KEY[key];
    if (!reg) return "";
    var parts = [];
    for (var k in params) {
      if (!Object.prototype.hasOwnProperty.call(params, k)) continue;
      var v = params[k];
      if (v === null || v === undefined || v === "") continue;
      parts.push(k + "=" + encVal(v));
    }
    return "#" + reg.slug + (parts.length ? "?" + parts.join("&") : "");
  }

  function hashFor(key) {
    var reg = BY_KEY[key];
    if (!reg) return "";
    return formatHash(key, reg.encode ? reg.encode() || {} : {});
  }

  // --- writing -------------------------------------------------------------

  function writeHash(h, push) {
    if (!h || h === curHash()) return; // no-op writes are the common case
    expected.push(h);
    if (push) location.hash = h; // pushes a history entry
    else location.replace(base() + h); // replaces the current entry
  }

  // The default report in its default state gets the bare root URL, with no
  // fragment at all. Removing a fragment is the one thing location.* cannot do
  // without risking a real navigation -- and a real navigation here means
  // reloading 8 MB. history.replaceState can do it, but throws SecurityError on
  // file:// in Chrome, so probe it and fall back to writing the explicit slug.
  function stripHash() {
    if (!curHash()) return true; // already bare
    try {
      history.replaceState(null, "", base());
      return true;
    } catch (e) {
      return false;
    }
  }

  function isBareDefault(h) {
    var reg = BY_KEY[DEFAULT_KEY];
    return !!reg && currentKey === DEFAULT_KEY && h === "#" + reg.slug;
  }

  function doWrite(push) {
    var h = hashFor(currentKey);
    // Strip only on replace writes. A push write is a report switch, and
    // replaceState would silently eat the history entry it was meant to create.
    if (!push && isBareDefault(h) && stripHash()) return;
    writeHash(h, push);
  }

  function scheduleWrite() {
    if (writeTimer) clearTimeout(writeTimer);
    writeTimer = setTimeout(function () {
      writeTimer = null;
      doWrite(false);
    }, WRITE_DELAY);
  }

  function flushPending() {
    if (!writeTimer) return;
    clearTimeout(writeTimer);
    writeTimer = null;
    doWrite(false);
  }

  // --- applying ------------------------------------------------------------

  function setActiveClasses(key) {
    var app = document.getElementById("app");
    if (app) {
      ORDER.forEach(function (k) {
        app.classList.toggle("show-" + k, k === key);
      });
    }
    // Keeps the dropdown in step with a pasted hash and with back/forward.
    var sel = document.getElementById("report-select");
    if (sel && sel.value !== key) sel.value = key;
  }

  function applyHash(route) {
    var reg = BY_KEY[route.key] || BY_KEY[DEFAULT_KEY];
    if (!reg) return;

    // A write queued before this navigation described the report we are leaving.
    // Drop it rather than let it fire 250ms from now over the one we are showing.
    if (writeTimer) {
      clearTimeout(writeTimer);
      writeTimer = null;
    }

    // Classes first: decode()'s control builders, and the draw that follows,
    // measure laid-out geometry, and a hidden pane has clientWidth 0.
    setActiveClasses(reg.key);
    currentKey = reg.key;

    if (reg.decode) {
      applying = true;
      try {
        reg.decode(route.params || {});
      } catch (e) {
        // A malformed hash must not wedge `applying` true forever.
        if (window.console) console.error("[router] decode failed: " + reg.key, e);
      }
      applying = false;
    }

    echoing = true;
    try {
      (reg.refresh || reg.render)();
    } finally {
      echoing = false;
    }

    // Canonicalize, once, from what the module actually holds now. The hash we
    // were handed may spell its slug in any case, may order its params
    // differently, may carry params equal to defaults -- and the draw above may
    // have self-healed part of the state (instant_yields drops a sortEra whose
    // column the current yield lacks). Rewriting here rather than from a
    // module's draw means it happens exactly once, after the heal, and for every
    // report including the ones that keep touch() off their draw path.
    // doWrite is a no-op when the hash already matches, and our own write comes
    // back as an expected echo, so this cannot loop.
    doWrite(false);
  }

  function onHashChange() {
    var h = curHash();
    if (expected.indexOf(h) >= 0) {
      expected.length = 0; // our own write echoing back
      return;
    }
    expected.length = 0;
    applyHash(parseHash(h));
  }

  // --- public --------------------------------------------------------------

  var Router = {
    register: function (spec) {
      if (!spec || !spec.key || !spec.slug || !spec.render) return;
      if (BY_KEY[spec.key]) return;
      BY_KEY[spec.key] = spec;
      BY_SLUG[spec.slug.toLowerCase()] = spec.key;
      ORDER.push(spec.key);
    },

    start: function () {
      started = true;
      applyHash(parseHash(curHash()));
      window.addEventListener("hashchange", onHashChange);
    },

    // "My state changed." Debounced replace-write. `key` is required and is
    // checked against the active report: every module render()s at init and on
    // resize while hidden, and a hidden report must never author the URL.
    touch: function (key) {
      // `echoing` means this draw came from the router's own applyHash, which
      // canonicalizes the URL itself once the draw is done -- so a touch from it
      // is redundant, and letting it through would give an encode/decode pair
      // that disagreed a way to ping-pong at WRITE_DELAY intervals.
      if (!started || applying || echoing) return;
      if (key !== currentKey) return;
      scheduleWrite();
    },

    // Report switch. Immediate, and pushes a history entry.
    go: function (key) {
      if (!BY_KEY[key] || key === currentKey) return;
      // Land the outgoing report's final filter state in the entry we are about
      // to leave, so Back returns to exactly what was on screen.
      flushPending();
      currentKey = key;
      setActiveClasses(key);
      doWrite(true);
      // location.hash fires hashchange asynchronously and we swallow it as an
      // echo, so draw now rather than waiting for the round trip.
      var reg = BY_KEY[key];
      (reg.refresh || reg.render)();
    },

    // Single dispatch point for "reflow whatever is on screen" (sidebar
    // resize/collapse). Replaces the if/else chain in app.js, which omitted
    // instant_yields, policies_performance and religion_performance and fell
    // through to the Building report's render() for all three.
    renderActive: function () {
      var reg = BY_KEY[currentKey];
      if (reg) reg.render();
    },

    get: function (key) {
      return BY_KEY[key] || null;
    },
    keys: function () {
      return ORDER.slice();
    },
    currentKey: function () {
      return currentKey;
    }
  };

  window.Explorer.Router = Router;
})();

/* =============================================================================
 * Explorer.Ser -- serializer primitives shared by every module's encode/decode.
 *
 * The modules hold their filter state as Sets of payload vocabulary strings
 * (eras, yields, belief types, combat classes, policy branches) plus a handful
 * of scalars. These turn that into short, stable, whitelisted URL params.
 * ========================================================================== */
(function () {
  "use strict";
  window.Explorer = window.Explorer || {};

  // A set that is legitimately EMPTY has to be distinguishable from an absent
  // param: every Building Type chip off means "match nothing", and that state
  // must survive a share. formatHash drops empty-string values, so an empty set
  // serializes to this sentinel instead. A single hyphen is never a member of
  // any era, yield, belief-type, combat-class or branch vocabulary -- note that
  // religion's bucket labels like "150-159" contain hyphens but are never equal
  // to one, so this must always be compared with === and never indexOf.
  var EMPTY = "-";

  function asArray(setOrArr) {
    if (!setOrArr) return [];
    if (setOrArr instanceof Set) {
      var o = [];
      setOrArr.forEach(function (v) {
        o.push(v);
      });
      return o;
    }
    return setOrArr.slice();
  }

  var Ser = {
    EMPTY: EMPTY,

    setEq: function (set, arr) {
      if (!set) return false;
      arr = arr || [];
      if (set.size !== arr.length) return false;
      for (var i = 0; i < arr.length; i++) if (!set.has(arr[i])) return false;
      return true;
    },

    // `order` gives a canonical member order (P.eraOrder, P.yields, ...) so the
    // same state always produces the same string regardless of click sequence.
    setOut: function (set, order) {
      if (!set || set.size === 0) return EMPTY;
      var out = [];
      var extra = [];
      if (order) {
        order.forEach(function (v) {
          if (set.has(v)) out.push(v);
        });
        set.forEach(function (v) {
          if (order.indexOf(v) < 0) extra.push(v);
        });
        extra.sort();
        out = out.concat(extra);
      } else {
        out = asArray(set);
        out.sort();
      }
      return out.join(",");
    },

    // `allowed` whitelists members, so a stale bookmark from before a data
    // rebuild degrades instead of carrying a phantom member that silently
    // filters everything out.
    setIn: function (str, allowed) {
      var out = new Set();
      if (str === undefined || str === null || str === "") return out;
      if (str === EMPTY) return out; // explicit empty
      String(str)
        .split(",")
        .forEach(function (v) {
          v = v.replace(/^\s+|\s+$/g, "");
          if (!v) return;
          if (allowed && allowed.indexOf(v) < 0) return;
          out.add(v);
        });
      return out;
    },

    // Same, but an absent param -- or one whose every member was rejected by the
    // whitelist -- falls back to the module default. Use this everywhere the
    // empty set is NOT a meaningful default (i.e. everywhere except
    // wonders.branches). The explicit EMPTY sentinel still wins.
    setInOr: function (str, allowed, dfltArr) {
      if (str === EMPTY) return new Set();
      var s = Ser.setIn(str, allowed);
      return s.size ? s : new Set(dfltArr || []);
    },

    intIn: function (str, lo, hi, dflt) {
      var n = parseInt(str, 10);
      if (isNaN(n) || n < lo || n > hi) return dflt;
      return n;
    },
    enumIn: function (str, allowed, dflt) {
      return allowed.indexOf(str) >= 0 ? str : dflt;
    },
    // Nullable string against a vocabulary. `dflt` may be null.
    strIn: function (str, allowed, dflt) {
      if (str === undefined || str === null || str === "") return dflt;
      if (allowed && allowed.indexOf(str) < 0) return dflt;
      return str;
    },
    boolOut: function (b) {
      return b ? "1" : "0";
    },
    boolIn: function (str, dflt) {
      if (str === "1") return true;
      if (str === "0") return false;
      return dflt;
    },

    // --- default-omitting writers (contract C1) -----------------------------
    put: function (params, key, value, dflt) {
      if (value === dflt) return;
      if (value === null || value === undefined) return;
      params[key] = String(value);
    },
    // The comparison happens BEFORE serialization, so a set whose default IS
    // empty (wonders.branches) is omitted rather than written as the sentinel.
    putSet: function (params, key, set, dfltArr, order) {
      if (Ser.setEq(set, dfltArr)) return;
      params[key] = Ser.setOut(set, order);
    }
  };

  window.Explorer.Ser = Ser;
})();
