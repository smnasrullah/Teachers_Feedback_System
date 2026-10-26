/* Feedback form: progress, "answer every required question" check, and the confirm dialog.
   The server re-checks everything; this only saves a round trip. Drafts and the comment
   pre-check are plain HTMX attributes in the markup. */
(function () {
  var form = document.querySelector("[data-feedback-form]");
  if (!form) {
    return;
  }
  var questions = Array.prototype.slice.call(form.querySelectorAll("[data-question]"));
  var required = questions.filter(function (box) {
    return box.hasAttribute("data-required");
  });
  var answeredOut = document.querySelector("[data-answered]");
  var progress = document.querySelector("[data-progress]");
  var summary = form.querySelector("[data-form-summary]");
  var dialog = document.getElementById("confirm-dialog");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function isAnswered(box) {
    var text = box.querySelector("textarea");
    if (text) {
      return text.value.trim().length > 0;
    }
    return box.querySelector("input:checked") !== null;
  }

  function mark(box, invalid) {
    box.classList.toggle("is-invalid", invalid);
    var message = box.querySelector(".fq-err");
    if (message) {
      message.hidden = !invalid;
    }
    var group = box.querySelector("[role=radiogroup]");
    if (group) {
      if (invalid) {
        group.setAttribute("aria-invalid", "true");
      } else {
        group.removeAttribute("aria-invalid");
      }
    }
  }

  function refresh() {
    var done = required.filter(isAnswered).length;
    if (answeredOut) {
      answeredOut.textContent = String(done);
    }
    if (progress) {
      progress.value = done;
    }
  }

  function firstControl(box) {
    return box.querySelector("input, textarea");
  }

  function reveal(box) {
    box.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
    var control = firstControl(box);
    if (control) {
      control.focus({ preventScroll: true });
    }
  }

  function review() {
    var missing = required.filter(function (box) {
      return !isAnswered(box);
    });
    questions.forEach(function (box) {
      mark(box, missing.indexOf(box) !== -1);
    });
    if (summary) {
      summary.hidden = missing.length === 0;
      if (missing.length) {
        summary.querySelector("span").textContent = summary.getAttribute("data-template").replace(
          "{count}",
          String(missing.length)
        );
      }
    }
    if (missing.length) {
      reveal(missing[0]);
      return;
    }
    if (dialog && dialog.showModal) {
      dialog.showModal();
    }
  }

  form.addEventListener("click", function (event) {
    if (event.target.closest("[data-review]")) {
      review();
    }
  });

  function onAnswer(event) {
    var box = event.target.closest("[data-question]");
    if (box && isAnswered(box)) {
      mark(box, false);
    }
    if (summary && !form.querySelector(".fq.is-invalid")) {
      summary.hidden = true;
    }
    refresh();
  }
  form.addEventListener("change", onAnswer);
  form.addEventListener("input", onAnswer);

  refresh();
  var firstInvalid = form.querySelector(".fq.is-invalid");
  if (dialog && dialog.hasAttribute("data-autoopen") && dialog.showModal) {
    dialog.showModal();
  } else if (firstInvalid) {
    reveal(firstInvalid);
  }
})();
