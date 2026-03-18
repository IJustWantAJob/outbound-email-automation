/* ======================================================================
   Email Campaign Manager — Fade animation (anime.js)
   Gentle opacity fade-in with subtle lift on page load.
   ====================================================================== */
(function () {
  if (typeof anime === 'undefined') return;

  requestAnimationFrame(function () {
    var header = document.querySelector('.page-header');
    var metrics = document.querySelectorAll('.metric-card');
    var cards = document.querySelectorAll('.card');
    var all = [];

    if (header) all.push(header);
    metrics.forEach(function (el) { all.push(el); });
    cards.forEach(function (el) { all.push(el); });
    if (!all.length) return;

    // Hide everything first
    all.forEach(function (el) { el.style.opacity = '0'; });

    // Failsafe: show everything after 2s no matter what
    var failsafe = setTimeout(function () {
      all.forEach(function (el) { el.style.opacity = '1'; el.style.transform = 'none'; });
    }, 2000);

    function done() { clearTimeout(failsafe); }

    if (header) anime({ targets: header, translateY: [-12, 0], opacity: [0, 1], duration: 500, easing: 'easeOutCubic' });
    if (metrics.length) anime({ targets: metrics, translateY: [20, 0], opacity: [0, 1], duration: 600, easing: 'easeOutCubic', delay: anime.stagger(80) });
    if (cards.length) anime({ targets: cards, translateY: [24, 0], opacity: [0, 1], duration: 700, easing: 'easeOutCubic', delay: anime.stagger(100, { start: 200 }), complete: done });
  });
})();
