/* Drag-to-reorder for lists marked [data-reorder]. The number inputs stay the source of truth
   (they work without JavaScript); dragging only moves the item and renumbers them. */
(function () {
  var dragged = null;

  function renumber(list) {
    list.querySelectorAll("[data-reorder-item]").forEach(function (item, index) {
      item.querySelector("[data-reorder-position]").value = String(index + 1);
    });
  }

  document.addEventListener("dragstart", function (event) {
    dragged = event.target.closest("[data-reorder-item]");
    if (dragged) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "");
    }
  });

  document.addEventListener("dragover", function (event) {
    var over = event.target.closest("[data-reorder-item]");
    if (!dragged || !over || over === dragged || over.parentNode !== dragged.parentNode) {
      return;
    }
    event.preventDefault();
    var after = event.clientY > over.getBoundingClientRect().top + over.offsetHeight / 2;
    over.parentNode.insertBefore(dragged, after ? over.nextSibling : over);
  });

  document.addEventListener("drop", function (event) {
    if (dragged) {
      event.preventDefault();
      renumber(dragged.parentNode);
    }
  });

  document.addEventListener("dragend", function () {
    dragged = null;
  });
})();
