/* Runs in <head> before first paint: applies the theme to <html>.
   Order: this browser's last choice (cookie), the signed-in person's saved theme, the system. */
(function () {
  var saved = document.cookie.match(/(?:^|; )tfs_theme=(light|dark)/);
  var preferred = document.documentElement.getAttribute("data-theme-pref");
  var choice = saved ? saved[1] : preferred;
  var dark = choice ? choice === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
})();
