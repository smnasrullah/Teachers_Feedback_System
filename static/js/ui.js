/* Progressive enhancement for design-system components. No inline handlers; everything keys off data-* attributes. */
(function () {
  var root = document.documentElement;

  function syncThemeButtons() {
    var dark = root.classList.contains("dark");
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(dark));
    });
  }

  function saveTheme(theme) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = "tfs_theme=" + theme + "; path=/; max-age=31536000; SameSite=Lax" + secure;
  }

  function closeMenus(except) {
    document.querySelectorAll("[data-toggle][aria-expanded='true']").forEach(function (button) {
      var menu = document.querySelector(button.getAttribute("data-toggle"));
      if (menu && menu !== except) {
        menu.hidden = true;
        button.setAttribute("aria-expanded", "false");
      }
    });
  }

  function updateRating(group) {
    var out = group.querySelector("[data-rate-out]");
    var checked = group.querySelector("input:checked");
    if (out && checked) {
      out.textContent = checked.value + " / 5 · " + checked.getAttribute("data-label");
    }
  }

  function armToast(toast) {
    if (toast.hasAttribute("data-autodismiss") && !toast.dataset.armed) {
      toast.dataset.armed = "1";
      window.setTimeout(function () {
        toast.remove();
      }, 8000);
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (target.closest("[data-print]")) {
      window.print();
      return;
    }

    var themeBtn = target.closest("[data-theme-toggle]");
    if (themeBtn) {
      var dark = !root.classList.contains("dark");
      root.classList.toggle("dark", dark);
      saveTheme(dark ? "dark" : "light");
      syncThemeButtons();
      return;
    }

    var toggle = target.closest("[data-toggle]");
    if (toggle) {
      var menu = document.querySelector(toggle.getAttribute("data-toggle"));
      var open = toggle.getAttribute("aria-expanded") === "true";
      closeMenus(menu);
      if (menu) {
        menu.hidden = open;
        toggle.setAttribute("aria-expanded", String(!open));
      }
      return;
    }
    if (!target.closest(".menu")) {
      closeMenus(null);
    }

    var opener = target.closest("[data-open]");
    if (opener) {
      var dialog = document.querySelector(opener.getAttribute("data-open"));
      if (dialog && dialog.showModal) {
        dialog.showModal();
      }
      return;
    }
    var closer = target.closest("[data-close]");
    if (closer) {
      var parent = closer.closest("dialog");
      if (parent) {
        parent.close();
      }
      return;
    }
    if (target.tagName === "DIALOG" && target.open) {
      target.close();
      return;
    }

    var dismiss = target.closest("[data-dismiss]");
    if (dismiss) {
      dismiss.closest(".toast").remove();
      return;
    }

    var pwToggle = target.closest("[data-pw-toggle]");
    if (pwToggle) {
      var wrap = pwToggle.closest(".pw-wrap");
      var input = wrap && wrap.querySelector("input");
      if (input) {
        var shown = input.type === "text";
        input.type = shown ? "password" : "text";
        pwToggle.setAttribute("aria-pressed", String(!shown));
      }
    }
  });

  function scorePassword(value) {
    if (!value) {
      return 0;
    }
    var score = 1;
    if (value.length >= 10) {
      score += 1;
    }
    if (/[A-Z]/.test(value) && /[a-z]/.test(value) && /\d/.test(value)) {
      score += 1;
    }
    if (value.length >= 14 || /[^A-Za-z0-9]/.test(value)) {
      score += 1;
    }
    return Math.min(4, score);
  }

  function updatePasswordStrength(input) {
    var field = input.closest(".field");
    var meter = field && field.querySelector("[data-pw-strength]");
    if (!meter) {
      return;
    }
    var score = scorePassword(input.value);
    meter.setAttribute("data-score", String(score));
    var label = meter.querySelector("[data-pw-strength-label]");
    if (label) {
      label.textContent = meter.getAttribute("data-level-" + score) || "";
    }
  }

  document.addEventListener("input", function (event) {
    if (event.target && event.target.matches('input[autocomplete="new-password"]')) {
      updatePasswordStrength(event.target);
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || event.defaultPrevented) {
      return;
    }
    var btn = form.querySelector('button[type="submit"]');
    if (btn) {
      btn.classList.add("is-loading");
      btn.setAttribute("aria-busy", "true");
    }
  });

  document.addEventListener("htmx:beforeRequest", function (event) {
    var elt = event.detail && event.detail.elt;
    var btn = elt && (elt.matches("button") ? elt : elt.querySelector('button[type="submit"]'));
    if (btn) {
      btn.classList.add("is-loading");
      btn.setAttribute("aria-busy", "true");
    }
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    var elt = event.detail && event.detail.elt;
    var btn = elt && (elt.matches("button") ? elt : elt.querySelector('button[type="submit"]'));
    if (btn) {
      btn.classList.remove("is-loading");
      btn.removeAttribute("aria-busy");
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    var expanded = document.querySelector("[data-toggle][aria-expanded='true']");
    if (expanded) {
      closeMenus(null);
      expanded.focus();
    }
  });

  document.addEventListener("change", function (event) {
    var group = event.target.closest("[data-rate]");
    if (group) {
      updateRating(group);
    }
  });

  document.querySelectorAll("[data-rate]").forEach(updateRating);
  document.querySelectorAll(".toast").forEach(armToast);
  var region = document.getElementById("toast-region");
  if (region) {
    new MutationObserver(function () {
      region.querySelectorAll(".toast").forEach(armToast);
    }).observe(region, { childList: true });
  }
  syncThemeButtons();
})();
