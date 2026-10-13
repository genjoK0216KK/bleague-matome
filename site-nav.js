/* Accessible mobile menu. Until initialization succeeds, all links stay visible. */
(function () {
  'use strict';
  var header = document.querySelector('.hdr');
  var button = header && header.querySelector('.nav-toggle');
  var nav = header && header.querySelector('#site-navigation');
  if (!button || !nav || !window.matchMedia) return;
  var mobile = window.matchMedia('(max-width: 899px)');
  var open = false;
  function setOpen(value, restoreFocus) {
    open = Boolean(value && mobile.matches);
    header.classList.toggle('nav-open', open);
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? 'メニューを閉じる' : 'メニューを開く');
    if (restoreFocus) button.focus();
  }
  button.addEventListener('click', function () { setOpen(!open, false); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false, true);
    }
  });
  document.addEventListener('click', function (event) {
    if (open && !header.contains(event.target)) setOpen(false, false);
  });
  nav.addEventListener('click', function (event) {
    if (event.target.closest('a')) setOpen(false, false);
  });
  function resized() { setOpen(false, false); }
  if (mobile.addEventListener) mobile.addEventListener('change', resized);
  else mobile.addListener(resized);
  // Only now is it safe to hide the fallback navigation on small screens.
  setOpen(false, false);
  header.classList.add('nav-enhanced');
  button.hidden = false;
})();
