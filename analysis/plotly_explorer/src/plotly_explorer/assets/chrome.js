/* Shared chrome: the two sidebars (collapse + drag-to-resize) and the window
   resize reflow. Each change reflows whichever report is on screen, through the
   router's registry.

   This used to live in app.js, the Building report, which tied the chrome to
   that report having data: a dataset without building yields would have left
   both sidebars unwired. */
(function () {
  "use strict";

  var SIDEBAR_MIN = 170;
  var SIDEBAR_MAX = 560;

  // The sidebars (collapse + drag-to-resize) are shared chrome owned by this
  // module, but a width change must reflow whichever report is currently shown.
  // Some reports need it more than others: the Leaders tables fit their block
  // seams to the measured pane width, so they have to re-fit on every change,
  // unlike the CSS-only reports.
  //
  // The router owns the key -> module registry, so dispatch goes there. This
  // used to be a second if/else chain over the show-* classes that had drifted
  // out of sync with the switcher: it omitted instant_yields,
  // policies_performance and religion_performance, and fell through to the
  // Building report's render() for all three -- reflowing a hidden report while
  // the visible one kept its stale width.
  function renderActive() {
    Explorer.Router.renderActive();
  }

  // Wire one collapse/expand pair + drag-to-resize handle.
  function makeSidebar(opts) {
    var app = document.getElementById("app");
    var sidebar = document.getElementById(opts.sidebarId);
    var resizer = document.getElementById(opts.resizerId);

    document
      .getElementById(opts.collapseBtnId)
      .addEventListener("click", function () {
        app.classList.add(opts.collapsedClass);
        renderActive();
      });
    document
      .getElementById(opts.expandBtnId)
      .addEventListener("click", function () {
        app.classList.remove(opts.collapsedClass);
        renderActive();
      });

    var dragging = false;
    var rafPending = false;

    function widthFromEvent(e) {
      // Left sidebar hugs the left edge (width == clientX); the right one hugs
      // the right edge (width == viewport width - clientX).
      var raw = opts.side === "left" ? e.clientX : window.innerWidth - e.clientX;
      return Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, raw));
    }

    function onMove(e) {
      if (!dragging) return;
      sidebar.style.width = widthFromEvent(e) + "px";
      if (!rafPending) {
        rafPending = true;
        requestAnimationFrame(function () {
          rafPending = false;
          renderActive();
        });
      }
    }

    function stop() {
      if (!dragging) return;
      dragging = false;
      resizer.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      renderActive();
    }

    resizer.addEventListener("mousedown", function (e) {
      dragging = true;
      resizer.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", stop);
  }

  function setupSidebar() {
    makeSidebar({
      side: "left",
      sidebarId: "sidebar",
      resizerId: "resizer",
      collapseBtnId: "collapse-btn",
      expandBtnId: "expand-btn",
      collapsedClass: "collapsed",
    });
    makeSidebar({
      side: "right",
      sidebarId: "sidebar-right",
      resizerId: "resizer-right",
      collapseBtnId: "collapse-btn-right",
      expandBtnId: "expand-btn-right",
      collapsedClass: "collapsed-right",
    });
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderActive, 150);
  });

  setupSidebar();
})();
