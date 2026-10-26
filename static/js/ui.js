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
