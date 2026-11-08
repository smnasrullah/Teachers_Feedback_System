/* Illustration runtime. Loops run only while their art is on screen and the tab is visible;
   .reveal blocks fade in once. All motion is off for prefers-reduced-motion and for
   <html data-motion="off">. */
(function () {
  var root = document.documentElement;
  root.classList.add("art-js");

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  function motionOff() {
    return reduce.matches || root.getAttribute("data-motion") === "off";
  }

  var visible = new Set();
  function sync() {
    document.querySelectorAll(".live").forEach(function (el) {
      el.classList.toggle("is-live", visible.has(el) && !document.hidden);
    });
  }

  if ("IntersectionObserver" in window) {
    var live = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            visible.add(entry.target);
          } else {
            visible.delete(entry.target);
          }
          entry.target.classList.toggle("is-live", entry.isIntersecting && !document.hidden);
        });
      },
      { threshold: 0.05 }
    );
    document.querySelectorAll(".live").forEach(function (el) {
      live.observe(el);
    });

    var reveal = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            reveal.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );
    document.querySelectorAll(".reveal").forEach(function (el) {
      reveal.observe(el);
    });
  } else {
    document.querySelectorAll(".live").forEach(function (el) {
      el.classList.add("is-live");
    });
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("is-in");
    });
  }
  document.addEventListener("visibilitychange", sync);

})();
