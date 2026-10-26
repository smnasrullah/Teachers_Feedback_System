htmx.config.allowEval = false;
htmx.config.allowScriptTags = false;
document.body.addEventListener("htmx:configRequest", function (event) {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) {
    event.detail.headers["X-CSRFToken"] = meta.content;
  }
});
