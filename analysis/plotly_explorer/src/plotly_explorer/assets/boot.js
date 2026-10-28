/* Dataset loader. Runs after the bundle is defined (as window.__explorerMain)
   and before any of it executes: every report module reads window.PAYLOAD as it
   loads, so PAYLOAD has to hold the dataset the URL names first.

   The dataset rides in the hash like every other piece of shareable state --
   #ReligionYields?ds=5_4_7&y=Gold -- and an absent ds means the default one.
   The default is inlined (#payload-default); any other is a sidecar
   datasets/<id>.js loaded by <script src>, which works over file:// where
   fetch() does not. Switching datasets reloads the page (see
   Router.setDataset), so this only ever runs once per page. */
(function () {
  "use strict";
  var M = window.EXPLORER_DATASETS;

  // Just enough of router.js's parseHash to find ds; the router re-parses the
  // whole hash once the bundle runs.
  function hashDataset() {
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

  function labelOf(id) {
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) return M.list[i].label;
    return null;
  }

  function useDefault(note) {
    window.PAYLOAD = JSON.parse(document.getElementById("payload-default").textContent);
    // switcher.js shows this under the Dataset dropdown; the router then drops
    // the ds the URL could not honour, so the URL matches what is shown.
    window.EXPLORER_DATASET_NOTE = note || null;
    window.__explorerMain();
  }

  var want = hashDataset();
  if (!want || want === M["default"]) return useDefault();
  if (labelOf(want) === null) {
    return useDefault('No dataset "' + want + '" in this build, showing the default.');
  }

  var failed = 'Could not load the "' + labelOf(want) + '" dataset, showing the default.';
  var script = document.createElement("script");
  script.src = M.dir + "/" + encodeURIComponent(want) + ".js";
  script.onload = function () {
    if (window.PAYLOAD && window.PAYLOAD.dataset === want) window.__explorerMain();
    else useDefault(failed);
  };
  script.onerror = function () {
    useDefault(failed);
  };
  document.head.appendChild(script);
})();
