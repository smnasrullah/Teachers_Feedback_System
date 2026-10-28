/* Pure time logic for the live clock and countdowns: no DOM, so node can test it. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.TFSClock = api;
  }
})(this, function () {
  var ZONE = "Asia/Dhaka";
  var LOCALES = {
    en: { date: "en-GB", time: "en-US", number: "en-US", hour12: true },
    bn: { date: "bn-BD", time: "bn-BD", number: "bn-BD", hour12: undefined },
  };
  var MAX_RELOAD_DELAY_MS = 3000;

  function localeOf(lang) {
    return LOCALES[String(lang).slice(0, 2)] || LOCALES.en;
  }

  /* serverMs - clientMs: add it to Date.now() to read the server's clock. */
  function computeOffset(serverMs, clientMs) {
    return serverMs - clientMs;
  }

  function parseUtc(iso) {
    return /Z$/.test(iso) ? Date.parse(iso) : NaN;
  }

  /* Whole seconds left, split into parts; a target in the past is "done". */
  function remaining(targetMs, nowMs) {
    var total = Math.max(0, Math.floor((targetMs - nowMs) / 1000));
    return {
      done: total === 0,
      days: Math.floor(total / 86400),
      hours: Math.floor((total % 86400) / 3600),
      minutes: Math.floor((total % 3600) / 60),
      seconds: total % 60,
    };
  }

  function digits(lang, minimum) {
    return new Intl.NumberFormat(localeOf(lang).number, {
      minimumIntegerDigits: minimum,
      useGrouping: false,
    });
  }

  /* "3d 04:05:06" with the language's digits; the day part is left out at zero days. */
  function formatCountdown(parts, lang, daysWord) {
    var two = digits(lang, 2);
    var clock = [parts.hours, parts.minutes, parts.seconds]
      .map(function (n) {
        return two.format(n);
      })
      .join(":");
    return parts.days > 0 ? digits(lang, 1).format(parts.days) + daysWord + " " + clock : clock;
  }

  /* The screen-reader sentence: template holds {days} {hours} {minutes}. */
  function formatSpoken(parts, lang, template) {
    var one = digits(lang, 1);
    return template
      .replace("{days}", one.format(parts.days))
      .replace("{hours}", one.format(parts.hours))
      .replace("{minutes}", one.format(parts.minutes));
  }

  /* Key that changes once a minute, which is how often the spoken text may change. */
  function minuteKey(parts) {
    return parts.done ? "done" : parts.days + ":" + parts.hours + ":" + parts.minutes;
  }

  function formatClock(nowMs, lang) {
    var locale = localeOf(lang);
    var moment = new Date(nowMs);
    return {
      date: new Intl.DateTimeFormat(locale.date, {
        timeZone: ZONE,
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(moment),
      time: new Intl.DateTimeFormat(locale.time, {
        timeZone: ZONE,
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: locale.hour12,
      }).format(moment),
      spoken: new Intl.DateTimeFormat(locale.date, {
        timeZone: ZONE,
        dateStyle: "full",
        timeStyle: "short",
        hour12: locale.hour12,
      }).format(moment),
    };
  }

  /* A random 0-3 s wait before the page reload, so a whole class does not reload at once. */
  function reloadDelay(random) {
    return Math.floor(random * MAX_RELOAD_DELAY_MS);
  }

  /* Milliseconds until the next whole second of the server clock. */
  function untilNextSecond(nowMs) {
    return 1000 - (((nowMs % 1000) + 1000) % 1000);
  }

  return {
    computeOffset: computeOffset,
    parseUtc: parseUtc,
    remaining: remaining,
    formatCountdown: formatCountdown,
    formatSpoken: formatSpoken,
    minuteKey: minuteKey,
    formatClock: formatClock,
    reloadDelay: reloadDelay,
    untilNextSecond: untilNextSecond,
  };
});
