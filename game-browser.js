document.querySelectorAll('.date-browser').forEach(function(browser) {
  var links = Array.from(browser.querySelectorAll('.date-chips a'));
  var panels = Array.from(browser.querySelectorAll('.date-panel'));
  function select(id) {
    if (!panels.some(function(p){return p.id === id;})) return;
    panels.forEach(function(p){p.hidden = p.id !== id;});
    links.forEach(function(a){if(a.hash === '#'+id) a.setAttribute('aria-current','date'); else a.removeAttribute('aria-current');});
  }
  select(location.hash.slice(1) || browser.dataset.default);
  links.forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();history.replaceState(null,'',a.hash);select(a.hash.slice(1));});});
  window.addEventListener('hashchange',function(){select(location.hash.slice(1));});
});
