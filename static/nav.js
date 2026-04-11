'use strict';
(function () {
  document.querySelectorAll('.nav-group').forEach(function (group) {
    var btn      = group.querySelector('.nav-group-btn');
    var dropdown = group.querySelector('.nav-dropdown');
    if (!btn || !dropdown) return;

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = group.classList.toggle('open');
      btn.setAttribute('aria-expanded', open);
    });
  });

  // Close all dropdowns when clicking outside
  document.addEventListener('click', function () {
    document.querySelectorAll('.nav-group.open').forEach(function (g) {
      g.classList.remove('open');
      var b = g.querySelector('.nav-group-btn');
      if (b) b.setAttribute('aria-expanded', 'false');
    });
  });

  // Close on Escape
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.nav-group.open').forEach(function (g) {
        g.classList.remove('open');
        var b = g.querySelector('.nav-group-btn');
        if (b) b.setAttribute('aria-expanded', 'false');
      });
    }
  });
}());
