/**
 * Shared navigation — included on every page.
 * Renders the main nav bar with auth-aware links.
 * Admin sub-nav shown only on /admin/* pages.
 */
// ---- Global time formatting — always IST (Asia/Kolkata) ----
(function() {
  const IST_OPTS_SHORT = { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false };
  const IST_OPTS_FULL  = { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false };
  const IST_OPTS_DATE  = { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' };
  const IST_OPTS_MY    = { timeZone: 'Asia/Kolkata', month: 'short', year: 'numeric' };
  const IST_OPTS_FMY   = { timeZone: 'Asia/Kolkata', month: 'long', year: 'numeric' };

  function parseUtc(s) {
    if (!s) return null;
    if (s instanceof Date) return s;
    // Accept ISO with/without Z; if no tz info, treat as UTC.
    const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(s);
    const d = new Date(hasTz ? s : (s.includes('T') ? s + 'Z' : s.replace(' ', 'T') + 'Z'));
    return isNaN(d.getTime()) ? null : d;
  }
  function format(d, opts) {
    return d.toLocaleString('en-GB', opts).replace(',', '') + ' IST';
  }

  window.fmtIST       = function(s) { const d = parseUtc(s); return d ? format(d, IST_OPTS_SHORT) : (s || ''); };
  window.fmtISTFull   = function(s) { const d = parseUtc(s); return d ? format(d, IST_OPTS_FULL)  : (s || ''); };
  window.fmtISTDate   = function(s) { const d = parseUtc(s); return d ? d.toLocaleString('en-GB', IST_OPTS_DATE) : (s || ''); };
  window.fmtISTMonthY = function(s) { const d = parseUtc(s); return d ? d.toLocaleString('en-GB', IST_OPTS_MY)   : (s || ''); };
  window.fmtISTFullMY = function(s) { const d = parseUtc(s); return d ? d.toLocaleString('en-GB', IST_OPTS_FMY)  : (s || ''); };
})();

(function() {
  const LOGO = '<svg width="24" height="24" viewBox="0 0 24 24" style="vertical-align:middle;margin-right:6px"><rect width="24" height="24" rx="5" fill="#e8a849"/><path d="M7 17L12 6L17 17" stroke="#0f1419" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="12" cy="10" r="2" fill="#0f1419"/><line x1="9" y1="14" x2="15" y2="14" stroke="#0f1419" stroke-width="1.5" stroke-linecap="round"/></svg>';

  // Inject favicon into <head> if missing (for backend-rendered pages)
  if (!document.querySelector('link[rel="icon"]')) {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    link.href = '/favicon.svg';
    document.head.appendChild(link);
  }

  const path = window.location.pathname;

  function isActive(href) {
    if (href === '/') return path === '/' || path === '/index.html';
    return path.startsWith(href);
  }

  function activeClass(href) {
    return isActive(href) ? ' class="active"' : '';
  }

  // On admin/account pages the user MUST be logged in, so show auth links immediately
  const requiresAuth = path.startsWith('/admin') || path.startsWith('/account');
  const authDisplay = requiresAuth ? 'inline' : 'none';
  const anonDisplay = requiresAuth ? 'none' : 'inline';
  const adminDisplay = path.startsWith('/admin') ? 'inline' : 'none';

  // Build main nav
  const nav = document.createElement('div');
  nav.id = 'shared-nav';
  nav.innerHTML = `
    <nav class="topnav">
      <div style="display:flex;align-items:center;margin-right:auto;gap:8px">
        <a href="/" class="topnav-brand" style="text-decoration:none;margin-right:0">${LOGO} AI Learning Roadmap<span id="planBadge"></span></a>
        <span id="connectionBadges" style="display:none">
          <span id="badgeGoogle" class="conn-badge" style="display:none">Google</span>
          <span id="badgeGithub" class="conn-badge" style="display:none">GitHub</span>
          <span id="badgeLinkedin" class="conn-badge" style="display:none">LinkedIn</span>
        </span>
      </div>
      <div class="topnav-links">
        <a href="/"${activeClass('/')}>Home</a>
        <a href="/leaderboard"${activeClass('/leaderboard')}>Leaderboard</a>
        <span id="navAuth" style="display:${authDisplay}">
          <a href="/account"${activeClass('/account')}>Account</a>
          <a href="/admin/" id="navAdminLink" style="display:${adminDisplay}"${activeClass('/admin')}>Admin</a>
          <a href="#" onclick="navSignOut();return false">Sign Out</a>
        </span>
        <span id="navAnon" style="display:${anonDisplay}">
          <a href="#" onclick="navSignIn();return false" class="signin-link">Sign In</a>
        </span>
      </div>
    </nav>
  `;

  // Admin sub-nav (only on /admin/* pages)
  if (path.startsWith('/admin')) {
    nav.innerHTML += `
      <nav class="subnav">
        <a href="/admin/"${path === '/admin/' ? ' class="active"' : ''}>Dashboard</a>
        <a href="/admin/users"${activeClass('/admin/users')}>Users</a>
        <a href="/admin/templates"${activeClass('/admin/templates')}>Templates</a>
        <a href="/admin/pipeline/"${activeClass('/admin/pipeline')}>Pipeline</a>
        <a href="/admin/pipeline/topics"${activeClass('/admin/pipeline/topics')}>Topics</a>
        <a href="/admin/pipeline/proposals"${activeClass('/admin/pipeline/proposals')}>Proposals</a>
        <a href="/admin/pipeline/settings"${activeClass('/admin/pipeline/settings')}>Settings</a>
        <a href="/admin/pipeline/ai-usage"${activeClass('/admin/pipeline/ai-usage')}>AI Usage</a>
      </nav>
    `;
  }

  // Insert at top of body
  document.body.insertBefore(nav, document.body.firstChild);

  // Check auth
  fetch('/api/auth/me', { credentials: 'same-origin' })
    .then(r => { if (r.ok) return r.json(); throw new Error(); })
    .then(user => {
      document.getElementById('navAuth').style.display = 'inline';
      document.getElementById('navAnon').style.display = 'none';
      if (user.is_admin) {
        document.getElementById('navAdminLink').style.display = '';
      }
      // Expose to page
      window._navUser = user;
      window.dispatchEvent(new Event('nav-auth-ready'));
    })
    .catch(() => {
      document.getElementById('navAuth').style.display = 'none';
      document.getElementById('navAnon').style.display = 'inline';
    });

  // Global sign out
  window.navSignOut = async function() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    window.location = '/';
  };

  // Global sign in — dispatch event for pages that have sign-in modals
  window.navSignIn = function() {
    if (typeof window.signIn === 'function') {
      window.signIn();
    } else {
      window.location = '/';
    }
  };
})();
