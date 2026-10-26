/* Mockup-only behaviour: theme, language, star-rating demo, form progress, dialog. Not production code. */
(function () {
  var root = document.documentElement;
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var theme = get("tfs-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  root.setAttribute("data-theme", theme);
  var lang = get("tfs-lang") || "bn";
  root.setAttribute("lang", lang);

  function syncLang() {
    document.querySelectorAll("[data-lang]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === root.lang));
    });
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-lang],[data-theme-toggle],[data-open],[data-close]");
    if (!t) return;
    if (t.hasAttribute("data-lang")) { root.lang = t.getAttribute("data-lang"); set("tfs-lang", root.lang); syncLang(); }
    if (t.hasAttribute("data-theme-toggle")) {
      var n = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", n); set("tfs-theme", n);
    }
    if (t.hasAttribute("data-open")) { var d = document.querySelector(t.getAttribute("data-open")); if (d && d.showModal) d.showModal(); }
    if (t.hasAttribute("data-close")) { var c = t.closest("dialog"); if (c) c.close(); }
  });
  syncLang();

  /* feedback form demo */
  var qs = document.querySelectorAll(".q[data-required]");
  if (qs.length) {
    var labels = { bn: ["", "খুবই খারাপ", "খারাপ", "মোটামুটি", "ভালো", "চমৎকার"], en: ["", "Poor", "Fair", "Good", "Very good", "Excellent"] };
    function answered(q) {
      var ta = q.querySelector("textarea");
      if (ta) return ta.value.trim().length >= 10;
      return !!q.querySelector("input:checked");
    }
    function update() {
      var n = 0;
      qs.forEach(function (q) {
        var ok = answered(q);
        if (ok) { n++; q.classList.remove("invalid"); var er = q.querySelector(".err"); if (er) er.hidden = true; }
        var rv = q.querySelector(".rate-val");
        var ch = q.querySelector(".rate input:checked");
        if (rv && ch) rv.textContent = ch.value + " / 5  " + labels[root.lang][+ch.value];
      });
      document.querySelectorAll("[data-answered]").forEach(function (el) { el.textContent = n; });
      var m = document.querySelector("[data-progress]");
      if (m) m.style.width = Math.round((n / qs.length) * 100) + "%";
    }
    document.addEventListener("input", update);
    document.addEventListener("change", update);
    var submit = document.querySelector("[data-submit]");
    if (submit) submit.addEventListener("click", function () {
      var first = null;
      qs.forEach(function (q) {
        if (!answered(q)) { q.classList.add("invalid"); var er = q.querySelector(".err"); if (er) er.hidden = false; if (!first) first = q; }
      });
      if (first) { first.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" }); }
      else { document.querySelector("#confirm").showModal(); }
    });
    update();
  }
})();
