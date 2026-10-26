htmx.config.allowEval = false;
htmx.config.allowScriptTags = false;
document.body.addEventListener("htmx:configRequest", function (event) {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) {
    event.detail.headers["X-CSRFToken"] = meta.content;
  }
});
// A rate-limited step answers 429 with the form and its message: show it like any other step.
document.body.addEventListener("htmx:beforeSwap", function (event) {
  if (event.detail.xhr.status === 429) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});
