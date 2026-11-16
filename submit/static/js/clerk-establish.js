// Runs on the "Signing you in" page (see auth/guard.py:establishing_session). If Clerk has a
// session, get a fresh token (which sets the __session cookie for this site) and reload; if
// not, go to sign-in. A counter in sessionStorage stops a reload loop if the cookie cannot be
// set (for example, cookies blocked).
(function () {
  var KEY = "coauthored_establish_tries";
  var box = document.getElementById("establish");
  var signIn = function () { window.location.assign(box.getAttribute("data-sign-in")); };
  var failed = function () { document.getElementById("establish-failed").hidden = false; };
  function ready() {
    if (!window.Clerk) { signIn(); return; }
    window.Clerk.load().then(function () {
      if (!window.Clerk.session) { sessionStorage.removeItem(KEY); signIn(); return; }
      var tries = Number(sessionStorage.getItem(KEY) || "0");
      if (tries >= 2) { sessionStorage.removeItem(KEY); failed(); return; }
      sessionStorage.setItem(KEY, String(tries + 1));
      window.Clerk.session.getToken({ skipCache: true }).then(function () {
        window.location.reload();
      }, failed);
    }, signIn);
  }
  var script = document.getElementById("clerk-js");
  if (window.Clerk) { ready(); }
  else if (script) {
    script.addEventListener("load", ready);
    script.addEventListener("error", signIn);
  } else { signIn(); }
})();
