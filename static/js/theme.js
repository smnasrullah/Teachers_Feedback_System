/* Runs in <head> before first paint: applies the saved (cookie) or system theme to <html>. */
(function () {
  var saved = document.cookie.match(/(?:^|; )tfs_theme=(light|dark)/);
  var dark = saved ? saved[1] === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
})();
