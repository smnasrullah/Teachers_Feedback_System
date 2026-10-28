/* Illustration runtime. Loops run only while their art is on screen and the tab is visible;
   .reveal blocks fade in once; the hero scene leans with the pointer. All motion is off for
   prefers-reduced-motion and for <html data-motion="off">. No inline styles: only CSSOM custom properties. */
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

  document.querySelectorAll("[data-parallax]").forEach(function (host) {
    var target = host.querySelector(".scene");
    if (!target || !window.matchMedia("(pointer: fine)").matches) {
      return;
    }
    var frame = 0;
    var next = 0;
    function paint() {
      frame = 0;
      target.style.setProperty("--px", next.toFixed(3));
    }
    function lean(value) {
      next = value;
      if (!frame) {
        frame = window.requestAnimationFrame(paint);
      }
    }
    host.addEventListener("pointermove", function (event) {
      if (motionOff()) {
        return;
      }
      var box = host.getBoundingClientRect();
      lean(((event.clientX - box.left) / box.width - 0.5) * -2);
    });
    host.addEventListener("pointerleave", function () {
      lean(0);
    });
  });
})();
