/* Development only: the "Fill in" buttons of the login page's demo box copy a demo account into the form. */
(function () {
  var box = document.querySelector("[data-demo-login]");
  var username = document.getElementById("id_username");
  var password = document.getElementById("id_password");
  if (!box || !username || !password) {
    return;
  }
  box.querySelectorAll("[data-fill-username]").forEach(function (button) {
    button.addEventListener("click", function () {
      username.value = button.getAttribute("data-fill-username");
      password.value = button.getAttribute("data-fill-password") || "";
      (password.value ? document.querySelector("form button[type='submit']") : password).focus();
    });
  });
})();
