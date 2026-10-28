/* Landing demo "See what your teacher sees". Everything is local to the page: nothing is sent anywhere.
   Stars and a comment merge into hardcoded sample totals; the combined bars grow, the comment lands among
   the others with no name and no time. */
(function () {
  var host = document.querySelector("[data-demo]");
  if (!host) {
    return;
  }
  var root = document.documentElement;
  var rows = Array.prototype.slice.call(host.querySelectorAll("[data-demo-row]"));
  var list = host.querySelector("[data-demo-comments]");
  var quote = host.querySelector("template[data-demo-quote]");
  var send = host.querySelector("[data-demo-send]");
  var reset = host.querySelector("[data-demo-reset]");
  var status = host.querySelector("[data-demo-status]");
  var slip = host.querySelector("[data-demo-slip]");
  var comment = host.querySelector("[data-demo-text]");
  var countOut = host.querySelector("[data-demo-count]");
  var panel = host.querySelector("[data-demo-panel]");
  var base = rows.map(function (row) {
    return { sum: Number(row.getAttribute("data-sum")), n: Number(row.getAttribute("data-n")) };
  });
  var shown = base.map(function (b) {
    return b.sum / b.n;
  });
  var total = Number(host.getAttribute("data-total"));
  var sent = false;

  host.querySelectorAll("[data-rate-out]").forEach(function (out) {
    out.setAttribute("data-initial", out.textContent);
  });

  function motionOff() {
    return (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      root.getAttribute("data-motion") === "off"
    );
  }
  function fmt(value, digits) {
    return value.toLocaleString("en", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function say(text) {
    status.textContent = text;
  }
  function paint(index, value) {
    var row = rows[index];
    row.querySelector("[data-demo-avg]").textContent = fmt(value, 1);
    row.querySelector(".bar-fill").style.setProperty("--v", (value / 5).toFixed(3));
  }
  function countUp(index, to) {
    var from = shown[index];
    shown[index] = to;
    if (motionOff() || from === to) {
      paint(index, to);
      return;
    }
    var start = performance.now();
    function step(now) {
      var t = Math.min((now - start) / 700, 1);
      paint(index, from + (to - from) * (1 - Math.pow(1 - t, 3)));
      if (t < 1) {
        window.requestAnimationFrame(step);
      }
    }
    window.requestAnimationFrame(step);
  }
  function picked(index) {
    var checked = host.querySelector("input[name='" + rows[index].getAttribute("data-name") + "']:checked");
    return checked ? Number(checked.value) : 0;
  }
  function fly(done) {
    if (motionOff() || !slip.animate) {
      done();
      return;
    }
    var from = send.getBoundingClientRect();
    var to = panel.getBoundingClientRect();
    var origin = host.getBoundingClientRect();
    var x1 = from.left - origin.left + from.width / 2 - 20;
    var y1 = from.top - origin.top;
    var x2 = to.left - origin.left + to.width / 2 - 20;
    var y2 = to.top - origin.top + 40;
    slip.hidden = false;
    var run = slip.animate(
      [
        { transform: "translate(" + x1 + "px," + y1 + "px) rotate(-6deg)", opacity: 1 },
        { transform: "translate(" + (x1 + x2) / 2 + "px," + (y1 - 36) + "px) rotate(8deg)", opacity: 1, offset: 0.5 },
        { transform: "translate(" + x2 + "px," + y2 + "px) rotate(0deg) scale(0.7)", opacity: 0 },
      ],
      { duration: 800, easing: "cubic-bezier(.4,0,.2,1)" }
    );
    run.onfinish = function () {
      slip.hidden = true;
      done();
    };
  }
  function cue(anchor) {
    if (motionOff()) {
      return;
    }
    var label = document.createElement("span");
    label.className = "demo-plus";
    label.setAttribute("aria-hidden", "true");
    label.textContent = host.getAttribute("data-msg-plus");
    anchor.appendChild(label);
    label.addEventListener("animationend", function () {
      label.remove();
    });
  }
  function mark(row) {
    row.classList.add("is-changed");
    if (!motionOff()) {
      window.setTimeout(function () {
        row.classList.remove("is-changed");
      }, 2600);
    }
  }
  function merge() {
    rows.forEach(function (row, index) {
      var stars = picked(index);
      if (stars) {
        countUp(index, (base[index].sum + stars) / (base[index].n + 1));
        mark(row);
        cue(host.querySelector("input[name='" + row.getAttribute("data-name") + "']").closest(".demo-q"));
      }
    });
    var text = comment.value.trim();
    if (text && quote) {
      var item = quote.content.firstElementChild.cloneNode(true);
      item.querySelector("p").textContent = text;
      item.classList.add("is-new");
      if (!rows.some(function (_, index) { return picked(index) > 0; })) {
        cue(comment.closest(".field"));
      }
      list.insertBefore(item, list.children[Math.floor(Math.random() * (list.children.length + 1))] || null);
    }
    countOut.textContent = fmt(total + 1, 0);
    say(host.getAttribute("data-msg-done").replace("{n}", fmt(total + 1, 0)));
  }

  send.addEventListener("click", function () {
    if (sent) {
      return;
    }
    var anyStars = rows.some(function (_, index) {
      return picked(index) > 0;
    });
    if (!anyStars && !comment.value.trim()) {
      say(host.getAttribute("data-msg-pick"));
      return;
    }
    sent = true;
    send.disabled = true;
    fly(merge);
  });
  reset.addEventListener("click", function () {
    sent = false;
    send.disabled = false;
    host.querySelectorAll("input[type='radio']").forEach(function (input) {
      input.checked = false;
    });
    host.querySelectorAll("[data-rate-out]").forEach(function (out) {
      out.textContent = out.getAttribute("data-initial");
    });
    comment.value = "";
    rows.forEach(function (row) {
      row.classList.remove("is-changed");
    });
    list.querySelectorAll(".is-new").forEach(function (item) {
      item.remove();
    });
    rows.forEach(function (_, index) {
      countUp(index, base[index].sum / base[index].n);
    });
    countOut.textContent = fmt(total, 0);
    say("");
  });
})();
