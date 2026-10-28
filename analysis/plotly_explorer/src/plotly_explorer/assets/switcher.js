/* Report switcher + router bootstrap. Loaded LAST, after every report module
   has called Explorer.Router.register(): Router.start() reads location.hash and
   renders the report it names, which only works once all ten are in the
   registry.

   This used to live at the tail of religion.js, where it ran mid-bundle with six
   of the ten modules still undefined and its `if (mod)` guard silently swallowed
   their render -- so a pasted #Wonders set the right class but never drew. In
   its own file at the end of the bundle, "module not yet defined" is
   unrepresentable. */
(function () {
  "use strict";
  var Router = window.Explorer && window.Explorer.Router;
  if (!Router) return;

  var sel = document.getElementById("report-select");
  if (sel) {
    sel.addEventListener("change", function () {
      Router.go(sel.value);
    });
  }

  // Dataset dropdown. Picking one reloads the page under the new ds (see
  // Router.setDataset), so the <select> is built once, from the loaded state.
  var dsSel = document.getElementById("dataset-select");
  if (dsSel) {
    var ds = Router.datasets();
    ds.list.forEach(function (d) {
      var opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.label;
      dsSel.appendChild(opt);
    });
    dsSel.value = ds.current;
    dsSel.addEventListener("change", function () {
      Router.setDataset(dsSel.value);
    });
  }
  // Set by boot.js when the URL named a dataset it could not load.
  var note = document.getElementById("dataset-note");
  if (note && window.EXPLORER_DATASET_NOTE) {
    note.textContent = window.EXPLORER_DATASET_NOTE;
    note.hidden = false;
  }

  // Reads location.hash, flips the show-* classes, syncs the <select>, decodes
  // the params into the target module and draws it. With no hash this lands on
  // PAYLOAD.defaultReport in its default state and writes nothing, leaving the
  // bare root URL intact.
  Router.start();
})();
