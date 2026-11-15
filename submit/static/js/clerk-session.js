// Loads Clerk's browser script so the __session cookie stays fresh (Clerk session tokens
// last about a minute), and signs out from the sign-out page. Pages work without it,
// except that Clerk sign-in needs it.
(function () {
  function ready() {
    if (!window.Clerk) { return; }
    window.Clerk.load().then(function () {
      var out = document.querySelector("[data-clerk-sign-out]");
      if (out) {
        var go = function () { window.Clerk.signOut({ redirectUrl: out.getAttribute("data-redirect") || "/" }); };
        out.addEventListener("click", go);
        go();
      }
    });
  }
  var script = document.getElementById("clerk-js");
  if (window.Clerk) { ready(); } else if (script) { script.addEventListener("load", ready); }
})();
