// Runs before the page is drawn: the full intro (chalkboard) plays only on the first visit, and never when
// Windows is set to reduce motion. (A plain script, so the choice is made before any animation starts.)
(function () {
  try {
    var seen = localStorage.getItem("rdps.introSeen");
    var calm = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!seen && !calm) document.documentElement.classList.add("intro-first");
  } catch (e) { /* private mode: short intro */ }
})();
