/* Subscribe-funnel ribbon — anonymous & logged-in flows.
 *
 * Anonymous:  4 buttons → /api/profile/subscribe-intent?channel=X (302 to login).
 * Logged in:  4 inline checkboxes reflecting notify_* state from /api/profile.
 *             Toggle → PATCH /api/profile { notify_X: bool } → toast on success.
 *
 * Dismissal: per-surface, persists 30 days via localStorage.
 *
 * Hosting page contract:
 *   <link rel="stylesheet" href="/subscribe-ribbon.css">
 *   <div id="subscribe-ribbon" data-surface="jobs|roadmap|blog|blog-post"></div>
 *   <script src="/subscribe-ribbon.js" defer></script>
 *
 * Defensive: any unexpected error reverts the ribbon to hidden state. We never
 * block the host page if our endpoints are unreachable.
 */

(function () {
  'use strict';

  var CHANNELS = [
    { key: 'jobs',         label: 'AI jobs',         field: 'notify_jobs' },
    { key: 'roadmap',      label: 'Course progress', field: 'notify_roadmap' },
    { key: 'new_courses',  label: 'New courses',     field: 'notify_new_courses' },
    { key: 'blog',         label: 'Blog posts',      field: 'notify_blog' }
  ];

  var DISMISS_DAYS = 30;
  var DISMISS_MS = DISMISS_DAYS * 24 * 60 * 60 * 1000;

  function dismissKey(surface) {
    return 'subscribe-ribbon:dismissed:' + surface;
  }

  function isDismissed(surface) {
    try {
      var raw = window.localStorage.getItem(dismissKey(surface));
      if (!raw) return false;
      var ts = parseInt(raw, 10);
      if (!isFinite(ts)) return false;
      return (Date.now() - ts) < DISMISS_MS;
    } catch (_) {
      return false;
    }
  }

  function setDismissed(surface) {
    try {
      window.localStorage.setItem(dismissKey(surface), String(Date.now()));
    } catch (_) { /* private mode / quota — degrade silently */ }
  }

  function escText(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function renderHead(titleText, ledeText) {
    return (
      '<div class="subscribe-ribbon-head">' +
        '<div>' +
          '<p class="subscribe-ribbon-title">' + escText(titleText) + '</p>' +
          '<p class="subscribe-ribbon-lede">' + escText(ledeText) + '</p>' +
        '</div>' +
        '<button type="button" class="subscribe-ribbon-dismiss" ' +
                'aria-label="Dismiss subscribe banner">×</button>' +
      '</div>'
    );
  }

  function renderAnonymous(root) {
    var btns = CHANNELS.map(function (ch) {
      var href = '/api/profile/subscribe-intent?channel=' + encodeURIComponent(ch.key);
      return (
        '<a class="subscribe-ribbon-btn" href="' + href + '">' +
          '<span class="subscribe-ribbon-btn-plus" aria-hidden="true">+</span>' +
          escText(ch.label) +
        '</a>'
      );
    }).join('');

    root.innerHTML =
      renderHead(
        'Stay in the loop',
        'Free weekly digest — pick what you want delivered Monday morning.'
      ) +
      '<div class="subscribe-ribbon-buttons" role="group" aria-label="Subscribe to channel">' +
        btns +
      '</div>';
  }

  function renderLoggedIn(root, profile) {
    var rows = CHANNELS.map(function (ch) {
      var checked = profile[ch.field] !== false; // default-on if undefined
      return (
        '<label class="subscribe-ribbon-check" data-channel="' + ch.key + '">' +
          '<input type="checkbox" data-field="' + ch.field + '"' +
                 (checked ? ' checked' : '') + '>' +
          '<span>' + escText(ch.label) + '</span>' +
        '</label>'
      );
    }).join('');

    root.innerHTML =
      renderHead(
        'Your subscriptions',
        'Toggle any channel — changes save instantly.'
      ) +
      '<div class="subscribe-ribbon-checkboxes" role="group" ' +
            'aria-label="Email subscription channels">' +
        rows +
      '</div>' +
      '<span class="subscribe-ribbon-status" data-status></span>';
  }

  /* Toast — global element, single instance per page. */
  var _toastEl = null;
  var _toastTimer = null;
  function ensureToast() {
    if (_toastEl) return _toastEl;
    var el = document.createElement('div');
    el.className = 'subscribe-ribbon-toast';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
    _toastEl = el;
    return el;
  }
  function showToast(msg) {
    var el = ensureToast();
    el.textContent = msg;
    el.setAttribute('data-show', '1');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () {
      el.removeAttribute('data-show');
    }, 2200);
  }

  function setStatus(root, msg, tone) {
    var el = root.querySelector('[data-status]');
    if (!el) return;
    el.textContent = msg || '';
    if (tone) el.setAttribute('data-tone', tone);
    else el.removeAttribute('data-tone');
    el.removeAttribute('data-faded');
    if (msg) {
      setTimeout(function () { el.setAttribute('data-faded', '1'); }, 1800);
    }
  }

  function wireDismiss(root, surface) {
    var btn = root.querySelector('.subscribe-ribbon-dismiss');
    if (!btn) return;
    btn.addEventListener('click', function () {
      setDismissed(surface);
      root.setAttribute('data-dismissed', '1');
    });
  }

  function wireCheckboxes(root) {
    var labels = root.querySelectorAll('.subscribe-ribbon-check');
    Array.prototype.forEach.call(labels, function (label) {
      var input = label.querySelector('input[type="checkbox"]');
      if (!input) return;
      input.addEventListener('change', function () {
        var field = input.getAttribute('data-field');
        var nextValue = input.checked;
        var prevValue = !nextValue;
        label.setAttribute('data-saving', '1');
        input.disabled = true;
        var payload = {};
        payload[field] = nextValue;
        fetch('/api/profile', {
          method: 'PATCH',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(function (resp) {
          if (resp.status === 401) {
            // Cookie expired mid-page — bounce to login, return here.
            window.location = '/?login=1&return=' +
              encodeURIComponent(window.location.pathname + window.location.search);
            return null;
          }
          if (!resp.ok) {
            throw new Error('PATCH failed: ' + resp.status);
          }
          return resp.json();
        }).then(function (json) {
          if (json === null) return;
          showToast(nextValue ? 'Subscribed' : 'Unsubscribed');
          setStatus(root, 'Saved');
        }).catch(function (_err) {
          input.checked = prevValue;
          setStatus(root, 'Could not save — try again', 'error');
        }).then(function () {
          label.removeAttribute('data-saving');
          input.disabled = false;
        });
      });
    });
  }

  function init() {
    var root = document.getElementById('subscribe-ribbon');
    if (!root) return;
    var surface = root.getAttribute('data-surface') || 'unknown';

    if (isDismissed(surface)) {
      root.setAttribute('data-dismissed', '1');
      return;
    }

    fetch('/api/profile', { credentials: 'same-origin' })
      .then(function (resp) {
        if (resp.status === 401) return null;
        if (!resp.ok) throw new Error('GET /api/profile ' + resp.status);
        return resp.json();
      })
      .then(function (profile) {
        if (profile) renderLoggedIn(root, profile);
        else         renderAnonymous(root);
        wireDismiss(root, surface);
        if (profile) wireCheckboxes(root);
        root.setAttribute('data-ready', '1');
      })
      .catch(function (_err) {
        // Profile probe failed unexpectedly — fall back to anonymous flow
        // so the funnel still works for visitors with flaky connections.
        renderAnonymous(root);
        wireDismiss(root, surface);
        root.setAttribute('data-ready', '1');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
