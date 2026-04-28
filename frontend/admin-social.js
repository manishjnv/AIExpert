/* admin-social.js — AutomateEdge admin social-post publish loop
 *
 * Handles 5 card actions on /admin/social/drafts:
 *   edit | publish | copy-open | mark-posted | discard
 *
 * Wired via delegated click on document. No framework. No build step.
 * ES2017+ (async/await, template literals, optional chaining).
 */

(function () {
  'use strict';

  // ─── IST timestamp (uses global if nav.js loaded first) ───────────────────
  function fmtIST(s) {
    if (typeof window.fmtIST === 'function') return window.fmtIST(s);
    return new Date(s).toLocaleString('en-IN');
  }

  // ─── Escape helper ─────────────────────────────────────────────────────────
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  // ─── Toast stack (bottom-right, max 3 visible) ─────────────────────────────
  let _toastStack = null;
  const _activeToasts = [];

  function ensureToastStack() {
    if (_toastStack) return _toastStack;
    _toastStack = document.createElement('div');
    _toastStack.className = 'admin-toast-stack';
    document.body.appendChild(_toastStack);
    return _toastStack;
  }

  /**
   * showToast(message, type, linkHref, linkLabel)
   * type: 'success' | 'error' | 'info'
   * linkHref / linkLabel optional — appends an anchor inside the toast.
   */
  function showToast(message, type, linkHref, linkLabel) {
    const stack = ensureToastStack();
    type = type || 'info';

    // Cap at 3 visible toasts — remove oldest
    while (_activeToasts.length >= 3) {
      const oldest = _activeToasts.shift();
      if (oldest && oldest.parentNode) oldest.remove();
    }

    const el = document.createElement('div');
    el.className = 'admin-toast ' + type;
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');

    let html = esc(message);
    if (linkHref && linkLabel) {
      html += ' <a href="' + esc(linkHref) + '" target="_blank" rel="noopener" ' +
              'style="color:inherit;text-decoration:underline">' + esc(linkLabel) + '</a>';
    }
    el.innerHTML = html;
    stack.appendChild(el);
    _activeToasts.push(el);

    // Trigger enter animation next tick
    requestAnimationFrame(function () { el.setAttribute('data-show', '1'); });

    setTimeout(function () {
      el.removeAttribute('data-show');
      setTimeout(function () {
        el.remove();
        const idx = _activeToasts.indexOf(el);
        if (idx !== -1) _activeToasts.splice(idx, 1);
      }, 300);
    }, 3000);
  }

  // ─── Fetch helper ──────────────────────────────────────────────────────────
  async function apiFetch(url, method, body) {
    const opts = {
      method: method || 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(url, opts);
    let data = null;
    try { data = await resp.json(); } catch (_) { /* no body */ }
    if (!resp.ok) {
      const detail = (data && data.detail) ? data.detail : resp.statusText;
      throw Object.assign(new Error(detail), { status: resp.status, detail });
    }
    return data;
  }

  // ─── Modal helper ──────────────────────────────────────────────────────────
  /**
   * openModal(title, bodyHtml) → { close(), body (the .admin-modal div) }
   * Escape or click-outside closes. Returns handle to add form elements + wire events.
   */
  function openModal(title, bodyHtml) {
    const overlay = document.createElement('div');
    overlay.className = 'admin-modal-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);

    overlay.innerHTML =
      '<div class="admin-modal">' +
        '<div class="admin-modal-title">' + esc(title) + '</div>' +
        '<div class="admin-modal-body">' + bodyHtml + '</div>' +
      '</div>';

    const modal = overlay.querySelector('.admin-modal');

    function close() {
      overlay.remove();
      document.removeEventListener('keydown', onKeydown);
    }

    function onKeydown(e) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('keydown', onKeydown);

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });

    document.body.appendChild(overlay);
    // Focus first focusable element
    requestAnimationFrame(function () {
      const first = modal.querySelector('textarea, input, button');
      if (first) first.focus();
    });

    return { close, body: modal };
  }

  /** Show inline error below a given reference element inside a modal. */
  function showModalError(modal, msg) {
    let errEl = modal.querySelector('.admin-modal-error');
    if (!errEl) {
      errEl = document.createElement('div');
      errEl.className = 'admin-modal-error';
      const actions = modal.querySelector('.admin-modal-actions');
      if (actions) actions.before(errEl);
      else modal.querySelector('.admin-modal-body').appendChild(errEl);
    }
    errEl.textContent = msg;
  }

  function clearModalError(modal) {
    const errEl = modal.querySelector('.admin-modal-error');
    if (errEl) errEl.textContent = '';
  }

  // ─── Card utilities ────────────────────────────────────────────────────────
  function getCard(button) {
    // Card div carries class .draft-card on the outer wrapper. Buttons also
    // carry data-post-id, so we MUST scope by class to avoid closest() returning
    // the button itself (Element.closest matches the element first).
    return button.closest('.draft-card');
  }

  // ─── Action: edit ──────────────────────────────────────────────────────────
  async function handleEdit(button) {
    const postId   = button.dataset.postId;
    const platform = button.dataset.platform;
    const card     = getCard(button);
    if (!card) return;

    const currentBody     = card.dataset.body || '';
    const currentHashtags = (() => {
      try { return JSON.parse(card.dataset.hashtagsJson || '[]'); }
      catch (_) { return []; }
    })();

    const maxLen = platform === 'twitter' ? 280 : 3000;
    const bodyHtml =
      '<label class="admin-modal-label">Post body</label>' +
      '<textarea class="admin-modal-textarea" id="edit-body" ' +
              'maxlength="' + maxLen + '" rows="6">' +
        esc(currentBody) +
      '</textarea>' +
      '<div class="admin-modal-charcount"><span id="edit-charcount">' +
        currentBody.length + '</span> / ' + maxLen + '</div>' +
      '<label class="admin-modal-label" style="margin-top:12px">Hashtags <span class="admin-modal-hint">(comma-separated — Twitter: 1-2, LinkedIn: 3-5, always end with #AutomateEdge)</span></label>' +
      '<input class="admin-modal-input" id="edit-hashtags" type="text" ' +
             'value="' + esc(currentHashtags.join(', ')) + '">' +
      '<div class="admin-modal-actions">' +
        '<button class="admin-modal-btn secondary" id="edit-cancel">Cancel</button>' +
        '<button class="admin-modal-btn primary" id="edit-save">Save draft</button>' +
      '</div>';

    const { close, body: modal } = openModal('Edit draft', bodyHtml);

    const ta        = modal.querySelector('#edit-body');
    const counter   = modal.querySelector('#edit-charcount');
    const tagsInput = modal.querySelector('#edit-hashtags');
    const saveBtn   = modal.querySelector('#edit-save');
    const cancelBtn = modal.querySelector('#edit-cancel');

    ta.addEventListener('input', function () {
      counter.textContent = ta.value.length;
    });

    cancelBtn.addEventListener('click', close);

    saveBtn.addEventListener('click', async function () {
      clearModalError(modal);
      const rawTags = tagsInput.value.split(',')
        .map(t => t.trim()).filter(Boolean);
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      try {
        const result = await apiFetch(
          '/admin/social/edit/' + postId, 'POST',
          { body: ta.value, hashtags: rawTags }
        );
        // Update card data attrs
        if (card) {
          card.dataset.body = ta.value;
          card.dataset.hashtagsJson = JSON.stringify(rawTags);
          // Re-render body preview if element with class draft-body exists
          const bodyEl = card.querySelector('.draft-body');
          if (bodyEl) bodyEl.textContent = ta.value;
          const tagsEl = card.querySelector('.draft-hashtags');
          if (tagsEl) tagsEl.textContent = rawTags.join(' ');
        }
        close();
        showToast('Draft saved', 'success');
      } catch (err) {
        showModalError(modal, err.detail || err.message || 'Save failed');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save draft';
      }
    });
  }

  // ─── Action: publish (direct Twitter API) ─────────────────────────────────
  async function handlePublish(button) {
    const postId = button.dataset.postId;
    const card   = getCard(button);

    if (!confirm('Publish this draft to X now? This is irreversible.')) return;

    try {
      const result = await apiFetch('/admin/social/publish/' + postId, 'POST');
      const url = result && result.published_url;
      showToast('Published to X.', 'success', url || null, url ? 'View tweet' : null);
      if (card) card.remove();
    } catch (err) {
      if (err.status === 503) {
        showToast('X publishing disabled. Use Copy + Mark as posted instead.', 'error');
      } else {
        showToast(err.detail || err.message || 'Publish failed', 'error');
      }
    }
  }

  // ─── Action: copy-open ────────────────────────────────────────────────────
  async function handleCopyOpen(button) {
    const platform   = button.dataset.platform;
    const sourceKind = button.dataset.sourceKind;
    const sourceSlug = button.dataset.sourceSlug;
    const card       = getCard(button);
    if (!card) return;

    const body     = card.dataset.body || '';
    const hashtags = (() => {
      try { return JSON.parse(card.dataset.hashtagsJson || '[]'); }
      catch (_) { return []; }
    })();

    const fullText = body + '\n\n' + hashtags.join(' ');

    // Attempt 1: modern clipboard API
    let copied = false;
    try {
      await navigator.clipboard.writeText(fullText);
      copied = true;
    } catch (_) { /* fall through */ }

    // Attempt 2: execCommand fallback
    if (!copied) {
      const ta = document.createElement('textarea');
      ta.value = fullText;
      ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try {
        copied = document.execCommand('copy');
      } catch (_) { /* fall through */ }
      ta.remove();
    }

    // Attempt 3: manual-copy modal
    if (!copied) {
      const bodyHtml =
        '<p style="color:#d0cbc2;font-size:13px;margin:0 0 8px">Copy this text manually:</p>' +
        '<textarea class="admin-modal-textarea" rows="8" readonly ' +
                  'onclick="this.select()" style="white-space:pre-wrap">' +
          esc(fullText) +
        '</textarea>' +
        '<div class="admin-modal-actions">' +
          '<button class="admin-modal-btn secondary" id="mc-close">Close</button>' +
        '</div>';
      const { close, body: modal } = openModal(
        'Copy text (' + (platform === 'twitter' ? 'X' : 'LinkedIn') + ')',
        bodyHtml
      );
      modal.querySelector('#mc-close').addEventListener('click', close);
      return;
    }

    const platformLabel = platform === 'twitter' ? 'X' : 'LinkedIn';
    showToast('Copied. Opening ' + platformLabel + '…', 'info');

    // Build share URL
    let shareUrl;
    if (platform === 'twitter') {
      shareUrl = 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(fullText);
    } else {
      // LinkedIn share-offsite (not deprecated shareArticle)
      const originUrl = (sourceKind === 'blog')
        ? window.location.origin + '/blog/' + (sourceSlug || '')
        : window.location.origin + '/roadmap/' + (sourceSlug || '');
      shareUrl = 'https://www.linkedin.com/sharing/share-offsite/?url=' +
                 encodeURIComponent(originUrl);
    }

    setTimeout(function () {
      window.open(shareUrl, '_blank', 'noopener,noreferrer');
    }, 600);
  }

  // ─── Action: mark-posted ──────────────────────────────────────────────────
  async function handleMarkPosted(button) {
    const postId = button.dataset.postId;
    const card   = getCard(button);

    const bodyHtml =
      '<label class="admin-modal-label">Where did you post it? Paste the live URL:</label>' +
      '<input class="admin-modal-input" id="mp-url" type="url" ' +
             'placeholder="https://x.com/…" autocomplete="off">' +
      '<div class="admin-modal-actions">' +
        '<button class="admin-modal-btn secondary" id="mp-cancel">Cancel</button>' +
        '<button class="admin-modal-btn primary" id="mp-save">Save</button>' +
      '</div>';

    const { close, body: modal } = openModal('Mark as posted', bodyHtml);

    const urlInput = modal.querySelector('#mp-url');
    const saveBtn  = modal.querySelector('#mp-save');
    const cancelBtn = modal.querySelector('#mp-cancel');

    cancelBtn.addEventListener('click', close);

    saveBtn.addEventListener('click', async function () {
      clearModalError(modal);
      const val = (urlInput.value || '').trim();
      if (!val.startsWith('http://') && !val.startsWith('https://')) {
        showModalError(modal, 'Please enter a full URL starting with http:// or https://');
        return;
      }
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      try {
        await apiFetch('/admin/social/mark-posted/' + postId, 'POST',
                       { published_url: val });
        close();
        showToast('Marked as posted.', 'success', val, 'View post');
        if (card) card.remove();
      } catch (err) {
        showModalError(modal, err.detail || err.message || 'Save failed');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
      }
    });
  }

  // ─── Action: discard ──────────────────────────────────────────────────────
  async function handleDiscard(button) {
    const postId = button.dataset.postId;
    const card   = getCard(button);

    const bodyHtml =
      '<p class="admin-modal-discard-lede">Discard this draft? Optionally explain why:</p>' +
      '<textarea class="admin-modal-textarea" id="discard-reason" rows="3" ' +
               'placeholder="Reason (optional)…"></textarea>' +
      '<div class="admin-modal-actions">' +
        '<button class="admin-modal-btn secondary" id="discard-cancel">Cancel</button>' +
        '<button class="admin-modal-btn danger" id="discard-confirm">Discard</button>' +
      '</div>';

    const { close, body: modal } = openModal('Discard draft', bodyHtml);

    const reasonTa  = modal.querySelector('#discard-reason');
    const cancelBtn = modal.querySelector('#discard-cancel');
    const discardBtn = modal.querySelector('#discard-confirm');

    cancelBtn.addEventListener('click', close);

    discardBtn.addEventListener('click', async function () {
      clearModalError(modal);
      discardBtn.disabled = true;
      discardBtn.textContent = 'Discarding…';
      try {
        await apiFetch('/admin/social/discard/' + postId, 'POST',
                       { reason: reasonTa.value || null });
        close();
        showToast('Discarded.', 'info');
        if (card) card.remove();
      } catch (err) {
        showModalError(modal, err.detail || err.message || 'Discard failed');
        discardBtn.disabled = false;
        discardBtn.textContent = 'Discard';
      }
    });
  }

  // ─── Action: re-publish (queues a fresh pending pair) ────────────────────
  async function handleRePublish(button) {
    const postId = button.dataset.postId;
    if (!confirm(
      'Queue a fresh draft pair for this source? Opus will be asked for a different angle on the next cron pass.'
    )) return;
    try {
      await apiFetch('/admin/social/re-publish/' + postId, 'POST');
      showToast('Re-publish queued. New drafts appear after the next cron pass.', 'success');
    } catch (err) {
      showToast(err.detail || err.message || 'Re-publish failed', 'error');
    }
  }

  // ─── Action: archive-stale-now (manual sweep trigger) ─────────────────────
  async function handleArchiveStaleNow() {
    if (!confirm('Archive all drafts older than 30 days now?')) return;
    try {
      const result = await apiFetch('/admin/social/archive-stale-now', 'POST');
      const n = (result && result.archived) || 0;
      showToast(`Archived ${n} stale draft(s).`, 'success');
      // Reload so the banner disappears + drafts refresh
      setTimeout(function () { window.location.reload(); }, 800);
    } catch (err) {
      showToast(err.detail || err.message || 'Sweep failed', 'error');
    }
  }

  // ─── Delegated click handler ───────────────────────────────────────────────
  function onDocClick(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    switch (action) {
      case 'edit':               handleEdit(btn);              break;
      case 'publish':            handlePublish(btn);           break;
      case 'copy-open':          handleCopyOpen(btn);          break;
      case 'mark-posted':        handleMarkPosted(btn);        break;
      case 'discard':            handleDiscard(btn);           break;
      case 're-publish':         handleRePublish(btn);         break;
      case 'archive-stale-now':  handleArchiveStaleNow();      break;
      default: break;
    }
  }

  // ─── Init ──────────────────────────────────────────────────────────────────
  function init() {
    document.addEventListener('click', onDocClick);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
