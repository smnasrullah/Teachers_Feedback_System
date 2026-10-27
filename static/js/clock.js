/* Live clock and countdowns. Reads the server's UTC time from <body data-server-now>, keeps the
   difference to the device clock, and drives every component from one shared timer. */
(function () {
  var core = window.TFSClock;
  var body = document.body;
  var lang = document.documentElement.lang || "en";
  var RESYNC_MIN_GAP_MS = 30000;
  var offset = core.computeOffset(core.parseUtc(body.dataset.serverNow), Date.now());
  var syncedAt = Date.now();
  var timer = null;
  var reloading = false;
  var clock = document.querySelector("[data-clock]");
  var countdowns = [];
  var lastSpokenClock = "";

  if (isNaN(offset)) {
    return;
  }

  function serverNow() {
    return Date.now() + offset;
  }

  function collect() {
    document.querySelectorAll("[data-countdown-to]").forEach(function (element) {
      if (element.dataset.ticking) {
        return;
      }
      var target = core.parseUtc(element.dataset.countdownTo);
      if (isNaN(target)) {
        return;
      }
      element.dataset.ticking = "1";
      countdowns.push({
        element: element,
        target: target,
        text: element.querySelector("[data-countdown-text]"),
        spoken: element.querySelector("[data-countdown-sr-text]"),
        spokenKey: "",
        wasRunning: core.remaining(target, serverNow()).done === false,
      });
    });
    countdowns = countdowns.filter(function (item) {
      return document.body.contains(item.element);
    });
  }

  function tickClock(now) {
    if (!clock) {
      return;
    }
    var parts = core.formatClock(now, lang);
    clock.hidden = false;
    clock.querySelector("[data-clock-date]").textContent = parts.date;
    clock.querySelector("[data-clock-time]").textContent = parts.time;
    if (parts.spoken !== lastSpokenClock) {
      lastSpokenClock = parts.spoken;
      clock.querySelector("[data-clock-sr]").textContent = parts.spoken;
    }
  }

  function reloadOnce() {
    if (reloading) {
      return;
    }
    reloading = true;
    window.setTimeout(function () {
      window.location.reload();
    }, core.reloadDelay(Math.random()));
  }

  function tickCountdown(item, now) {
    var parts = core.remaining(item.target, now);
    var element = item.element;
    var label = element.dataset.countdownLabel;
    item.text.textContent = parts.done
      ? element.dataset.countdownDone
      : core.formatCountdown(parts, lang, element.dataset.countdownDays);
    element.classList.toggle("is-done", parts.done);
    var key = core.minuteKey(parts);
    if (key !== item.spokenKey) {
      var first = item.spokenKey === "";
      item.spokenKey = key;
      item.spoken.textContent = parts.done
        ? element.dataset.countdownDone
        : label + " " + core.formatSpoken(parts, lang, element.dataset.countdownSr);
      if (first) {
        item.spoken.setAttribute("aria-live", "polite");
      }
    }
    if (parts.done && item.wasRunning) {
      item.wasRunning = false;
      reloadOnce();
    }
  }

  function tick() {
    var now = serverNow();
    tickClock(now);
    countdowns.forEach(function (item) {
      tickCountdown(item, now);
    });
    schedule();
  }

  function schedule() {
    window.clearTimeout(timer);
    timer = document.hidden ? null : window.setTimeout(tick, core.untilNextSecond(serverNow()));
  }

  function resync() {
    if (!body.dataset.timeUrl || Date.now() - syncedAt < RESYNC_MIN_GAP_MS) {
      return Promise.resolve();
    }
    var sent = Date.now();
    return fetch(body.dataset.timeUrl, { cache: "no-store", credentials: "omit" })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        var server = data && core.parseUtc(data.now);
        if (server) {
          var received = Date.now();
          offset = core.computeOffset(server, (sent + received) / 2);
          syncedAt = received;
        }
      })
      .catch(function () {});
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      window.clearTimeout(timer);
      timer = null;
      return;
    }
    resync().then(tick);
  });

  document.addEventListener("htmx:afterSettle", function () {
    collect();
    tick();
  });

  collect();
  tick();
})();
