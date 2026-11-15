// Progressive enhancement: show only the fields that apply to each author's kind.
// Without JavaScript every field is shown, labelled "Human authors" / "AI authors".
(function () {
  function sync(select) {
    var row = select.closest("fieldset.author");
    if (!row) { return; }
    var ai = select.value === "ai";
    // A group holding an error stays visible so the message can be read and fixed.
    var hide = function (el, h) { el.hidden = h && !el.querySelector("[aria-invalid=true]"); };
    row.querySelectorAll(".ai-only").forEach(function (el) { hide(el, !ai); });
    row.querySelectorAll(".human-only").forEach(function (el) { hide(el, ai); });
  }
  document.querySelectorAll("select[data-author-kind]").forEach(function (select) {
    sync(select);
    select.addEventListener("change", function () { sync(select); });
  });
})();
