(function () {
  var bar = document.querySelector(".topbar");
  if (bar) {
    var onScroll = function () {
      bar.classList.toggle("is-scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  document.querySelectorAll(".nav-links a, .nav-signout button").forEach(function (link) {
    link.addEventListener("click", function () {
      var box = document.querySelector(".nav-check");
      if (box) box.checked = false;
    });
  });

  document.querySelectorAll(".filters").forEach(function (toolbar) {
    var scope = document.getElementById("content") || document.body;
    var rows = scope.querySelectorAll("[data-track]");
    var empty = scope.querySelector(".empty");
    if (!rows.length) return;

    toolbar.addEventListener("click", function (event) {
      var button = event.target.closest("[data-filter]");
      if (!button || !toolbar.contains(button)) return;
      var filter = button.getAttribute("data-filter");
      toolbar.querySelectorAll(".chip").forEach(function (chip) {
        chip.classList.toggle("is-on", chip === button);
      });
      var visible = 0;
      rows.forEach(function (row) {
        var show = filter === "all" || row.getAttribute("data-track") === filter;
        row.hidden = !show;
        if (show) visible += 1;
      });
      scope.querySelectorAll(".day").forEach(function (day) {
        var any = day.querySelectorAll("[data-track]:not([hidden])").length > 0;
        day.hidden = !any;
      });
      if (empty) empty.hidden = visible !== 0;
    });
  });

  var purpose = document.querySelector("#purpose");
  if (purpose) {
    var sync = function () {
      var filing = purpose.value === "paper";
      document.querySelectorAll(".paper-only").forEach(function (node) {
        node.hidden = !filing;
      });
      document.querySelectorAll(".seat-only").forEach(function (node) {
        node.hidden = filing;
      });
    };
    purpose.addEventListener("change", sync);
    sync();
  }

  var mail = document.querySelector("[data-mail]");
  var providerNode = document.getElementById("mail-providers");
  var hint = document.getElementById("provider-hint");
  if (mail && providerNode && hint) {
    var names = JSON.parse(providerNode.textContent);
    var showMail = function () {
      var domain = (mail.value.split("@")[1] || "").trim().toLowerCase();
      if (!domain || domain.indexOf(".") === -1) {
        hint.hidden = true;
        return;
      }
      var label = names[domain] || "Other mail";
      hint.hidden = false;
      hint.textContent = label === "Other mail"
        ? "School and other addresses are welcome."
        : label + " is welcome.";
    };
    mail.addEventListener("input", showMail);
    showMail();
  }
})();
