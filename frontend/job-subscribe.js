/* job-subscribe.js — per-company job-alert toggle on the job detail page.
 * Mounts on #job-subscribe (data-company, data-company-name). Logged-in users
 * toggle an email subscription via /api/jobs/{subscribe,unsubscribe};
 * anonymous users are sent to sign in. Phase 1 = email channel. */
(function () {
  var mount = document.getElementById("job-subscribe");
  if (!mount) return;
  var slug = mount.dataset.company;
  var cname = mount.dataset.companyName || slug;
  if (!slug) return;

  var btn = document.createElement("button");
  btn.type = "button";
  btn.style.cssText =
    "display:inline-flex;align-items:center;gap:8px;background:#1a2029;color:#e8a849;" +
    "border:1px solid #2a323d;padding:9px 16px;border-radius:6px;font-size:14px;" +
    "font-weight:600;cursor:pointer;font-family:inherit;margin:4px 0 18px";
  mount.appendChild(btn);

  var subscribed = false, authed = false, busy = false;

  function render() {
    if (!authed) {
      btn.textContent = "🔔 Get alerts for new " + cname + " jobs";
      btn.style.color = "#e8a849"; btn.style.borderColor = "#2a323d";
      return;
    }
    btn.textContent = subscribed
      ? "✓ Following " + cname + " — alerts on (click to stop)"
      : "🔔 Get alerts for new " + cname + " jobs";
    btn.style.color = subscribed ? "#6db585" : "#e8a849";
    btn.style.borderColor = subscribed ? "#6db585" : "#2a323d";
  }

  function toast(msg) {
    var t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#161c24;" +
      "color:#f5f1e8;border:1px solid #2a323d;padding:10px 18px;border-radius:6px;" +
      "font-size:13px;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.4)";
    document.body.appendChild(t);
    setTimeout(function () {
      t.style.transition = "opacity .4s"; t.style.opacity = "0";
      setTimeout(function () { t.remove(); }, 400);
    }, 2600);
  }

  async function init() {
    try {
      var r = await fetch("/api/jobs/subscriptions", { credentials: "same-origin" });
      if (r.status === 401) { authed = false; render(); return; }
      if (r.ok) {
        authed = true;
        var data = await r.json();
        subscribed = (data.subscriptions || []).some(function (s) {
          return s.company_slug === slug && s.channel === "email";
        });
      }
    } catch (e) { /* leave anonymous */ }
    render();
  }

  btn.addEventListener("click", async function () {
    if (busy) return;
    if (!authed) { window.location.href = "/api/auth/google/login"; return; }
    busy = true;
    var want = !subscribed;
    subscribed = want; render();  // optimistic
    try {
      var r = await fetch(want ? "/api/jobs/subscribe" : "/api/jobs/unsubscribe", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_slug: slug, channel: "email" }),
      });
      if (!r.ok) { subscribed = !want; render(); }
      else {
        toast(want
          ? "You'll get email alerts for new " + cname + " jobs."
          : "Stopped alerts for " + cname + ".");
      }
    } catch (e) { subscribed = !want; render(); }
    busy = false;
  });

  init();
})();
