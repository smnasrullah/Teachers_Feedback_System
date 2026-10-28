const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../static/js/clock_core.js");

const NOW = Date.parse("2026-10-27T10:00:00.000Z");

test("offset corrects a device clock that is wrong", () => {
  const server = Date.parse("2026-10-27T10:00:00Z");
  const wrongDevice = server + 3600 * 1000;
  assert.equal(core.computeOffset(server, wrongDevice), -3600 * 1000);
  assert.equal(wrongDevice + core.computeOffset(server, wrongDevice), server);
});

test("parseUtc accepts only UTC timestamps", () => {
  assert.equal(core.parseUtc("2026-10-27T10:00:00.000Z"), NOW);
  assert.ok(Number.isNaN(core.parseUtc("2026-10-27T10:00:00+06:00")));
  assert.ok(Number.isNaN(core.parseUtc("")));
});

test("remaining splits into days, hours, minutes, seconds", () => {
  const target = NOW + ((3 * 24 + 4) * 3600 + 5 * 60 + 6) * 1000 + 999;
  assert.deepEqual(core.remaining(target, NOW), {
    done: false, days: 3, hours: 4, minutes: 5, seconds: 6,
  });
});

test("zero state: reached or past targets are done and never negative", () => {
  for (const target of [NOW, NOW - 1, NOW - 86400000, NOW + 999]) {
    const parts = core.remaining(target, NOW);
    assert.equal(parts.done, true);
    assert.deepEqual([parts.days, parts.hours, parts.minutes, parts.seconds], [0, 0, 0, 0]);
  }
});

test("formatCountdown pads, drops zero days, and localizes digits", () => {
  const parts = core.remaining(NOW + (2 * 86400 + 3 * 3600 + 4 * 60 + 5) * 1000, NOW);
  assert.equal(core.formatCountdown(parts, "en", "d"), "2d 03:04:05");
  assert.equal(core.formatCountdown(core.remaining(NOW + 65000, NOW), "en", "d"), "00:01:05");
  assert.equal(core.formatCountdown(parts, "bn", "দিন"), "২দিন ০৩:০৪:০৫");
});

test("formatSpoken fills the template and omits seconds", () => {
  const parts = core.remaining(NOW + (86400 + 2 * 3600 + 3 * 60 + 59) * 1000, NOW);
  assert.equal(
    core.formatSpoken(parts, "en", "{days} days, {hours} hours, {minutes} minutes"),
    "1 days, 2 hours, 3 minutes"
  );
});

test("minuteKey changes once a minute and on done", () => {
  const a = core.remaining(NOW + 125000, NOW);
  const b = core.remaining(NOW + 124000, NOW);
  const c = core.remaining(NOW + 59000, NOW);
  assert.equal(core.minuteKey(a), core.minuteKey(b));
  assert.notEqual(core.minuteKey(b), core.minuteKey(c));
  assert.equal(core.minuteKey(core.remaining(NOW, NOW)), "done");
});

test("formatClock shows Asia/Dhaka time: 12-hour in English, Bangla digits in Bangla", () => {
  const en = core.formatClock(Date.parse("2026-10-27T18:30:05Z"), "en");
  assert.match(en.time, /^12:30:05\sAM$/);
  assert.match(en.date, /28 Oct 2026/);
  const bn = core.formatClock(Date.parse("2026-10-27T18:30:05Z"), "bn");
  assert.match(bn.time, /^[০-৯]{2}:[০-৯]{2}:[০-৯]{2}/);
});

test("reloadDelay stays within 0-3 seconds", () => {
  assert.equal(core.reloadDelay(0), 0);
  assert.equal(core.reloadDelay(0.5), 1500);
  assert.ok(core.reloadDelay(0.999999) < 3000);
});

test("untilNextSecond lands on the next whole second", () => {
  assert.equal(core.untilNextSecond(NOW), 1000);
  assert.equal(core.untilNextSecond(NOW + 250), 750);
});
