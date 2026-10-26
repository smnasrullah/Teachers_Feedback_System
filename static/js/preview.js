/* Landing-page dashboard preview: an accessible tablist (arrow keys, Home, End) on the Alpine CSP build. */
document.addEventListener("alpine:init", function () {
  var ROLES = ["student", "teacher", "hod", "admin"];

  window.Alpine.data("dashPreview", function () {
    var state = {
      role: "student",
      pick: function (event) {
        this.select(event.currentTarget.getAttribute("data-role"), false);
      },
      key: function (event) {
        var at = ROLES.indexOf(this.role);
        var next = {
          ArrowRight: (at + 1) % ROLES.length,
          ArrowLeft: (at + ROLES.length - 1) % ROLES.length,
          Home: 0,
          End: ROLES.length - 1,
        }[event.key];
        if (next === undefined) {
          return;
        }
        event.preventDefault();
        this.select(ROLES[next], true);
      },
      select: function (role, focus) {
        this.role = role;
        if (focus) {
          this.$root.querySelector("#pv-tab-" + role).focus();
        }
      },
    };
    ROLES.forEach(function (role) {
      Object.defineProperty(state, role + "Sel", {
        enumerable: true,
        get: function () {
          return this.role === role ? "true" : "false";
        },
      });
      Object.defineProperty(state, role + "Idx", {
        enumerable: true,
        get: function () {
          return this.role === role ? 0 : -1;
        },
      });
      Object.defineProperty(state, role + "Hide", {
        enumerable: true,
        get: function () {
          return this.role !== role;
        },
      });
    });
    return state;
  });
});
