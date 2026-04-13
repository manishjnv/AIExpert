# Course Completion Certificates

Flow from learner completing their course to a recruiter verifying the credential.

## Completion tiers

| Tier | Trigger |
|---|---|
| **Completion** | ≥ 90% of all checklist items done **and** capstone month (final month) ≥ 100% complete |
| **With Distinction** | 100% of checklist items **and** ≥ 80% of `repos_required` linked by the learner |
| **With Honors** | Distinction criteria **plus** at least one AI repo evaluation score ≥ 8.0/10 on a capstone repo |

Gating on the capstone month (not just overall %) ensures the learner has shipped the final project, not only ticked theory weeks.

## Idempotence

One certificate per `(user_id, user_plan_id)`. Re-enrolling in the same template (which reactivates the old `UserPlan`) keeps the original certificate with its original issued date. Switching to a new plan does not invalidate past certificates.

## Credential ID format

`AER-YYYY-MM-XXXXXX` where `XXXXXX` is a 6-character alphanumeric code (uppercase). Examples: `AER-2026-04-A7F3K9`, `AER-2026-04-B2N8HP`. Embedded in the QR on the PDF; acts as the URL slug for the public verification page (`/verify/<credential_id>`).

## Display name

Snapshotted from `User.name` at issuance time. Editing the profile name later does **not** retro-update issued certificates. This is intentional — a certificate is a point-in-time credential; the recruiter should see the name the learner had when they earned it.

An inline note on the account page's Name field reminds the user: *"This name appears on your course completion certificate."*

## Tamper-evident verification

Each certificate has a `signed_hash`: `HMAC-SHA256(credential_id + '|' + user_id + '|' + issued_at_iso, secret=ANTHROPIC_ADMIN_API_KEY_or_CERT_SECRET)`. The public verification page recomputes and compares; a match renders a green ✓ *"Credential verified"* badge.

## Lifecycle

- **issued** — default state; certificate appears on learner's profile and verifies publicly.
- **revoked** — admin-only; public verification page still loads but shows a red ✗ *"Revoked"* badge with the reason. PDF download disabled. Used for fraud / data-integrity events only.

## Analytics tracked per certificate

- `pdf_downloads` — increments when learner downloads the PDF
- `linkedin_shares` — increments when learner clicks Share on LinkedIn
- `verification_views` — increments on public verification page load (cached per-IP to avoid inflation from refresh)

## Data model

See [backend/app/models/certificate.py](backend/app/models/certificate.py). Migration: `b3f5a9e21c04_add_certificates_table.py`.

## Implementation log

- **Step 1** (2026-04-13) — Certificate ORM model + Alembic migration `b3f5a9e21c04` + this design doc.
- **Step 8** (2026-04-13) — LinkedIn share button. Consolidated here: the share flow hits `POST /api/certificates/{id}/share-linkedin` (increments `linkedin_shares`) fire-and-forget, then opens `https://www.linkedin.com/sharing/share-offsite/?url=<verify_url>` in a new tab. Buttons wired in: (a) `/account` → My Certificates row, (b) home-page completion modal primary CTA, (c) public `/verify/{id}` page for recruiter-initiated re-shares (this one doesn't increment the counter — anonymous visitor). The feed-composer share URL works without a LinkedIn Company Page; OG meta tags on the verify page render the polished link card.
- **Step 7** (2026-04-13) — Profile name callout. Inline hint added under the Name field on /account explaining that it appears on certificates and recruiters will see it. Matches the snapshot-at-issue-time rule documented above (no retro-update after issuance).
- **Step 6** (2026-04-13) — Completion modal on home. When a progress tick succeeds with `done=true` the frontend polls `/api/certificates`; if the newest cert hasn't been shown for its (credential_id, tier) before (gated in localStorage so upgrades from completion→distinction→honors each fire once), a confetti modal pops with tier-specific copy and three CTAs: Download PDF, Share on LinkedIn, View in My Certificates. Closes on ×, overlay click, or navigation. Modal styles are scoped + injected inline to avoid bleed into the main page.
- **Step 5** (2026-04-13) — My Certificates on /account. New section below Preferences lists all of the current user's certificates (newest first) with tier badge, issued date, credential ID, and four per-row actions: Download PDF, Share on LinkedIn, Copy verification link, View public page. Revoked certs disable the PDF/share buttons. Uses `GET /api/certificates`; share button POSTs to `.../share-linkedin` (fire-and-forget) before opening the LinkedIn feed composer in a new tab.
- **Step 4** (2026-04-13) — Public verification page. `routers/verify.py` serves `GET /verify/{credential_id}` (HTML) and `GET /verify/{credential_id}/og.svg` (1200×630 link preview). Server-side HMAC check on every render drives the tamper-evident badge: green ✓ when signature + not-revoked, red ✗ for mismatch or revoked (with reason). Rate-limited to 60 IP·hour; `verification_views` increments at most once per (IP, credential) per hour to resist refresh inflation. OG meta tags render name, tier, course so LinkedIn / Twitter show a polished card.
- **Step 3** (2026-04-13) — PDF generator. `services/certificate_pdf.py` renders `templates/certificate.html` via Jinja2 → WeasyPrint → PDF bytes. A4 landscape, amber brand, embedded QR (base64 inline) pointing at the verify URL, tier badge for Distinction/Honors. Endpoints in `routers/certificates.py`: `GET /api/certificates`, `GET /api/certificates/{id}/pdf` (increments `pdf_downloads`, 410 on revoked), `POST /api/certificates/{id}/share-linkedin`. Dockerfile gains pango/cairo/harfbuzz/gdk-pixbuf system deps; `weasyprint==62.3` + `qrcode[pil]==7.4.2` added to requirements. WeasyPrint import is lazy so the pango load only happens on first PDF download.
- **Step 2** (2026-04-13) — Issuance engine landed in [backend/app/services/certificates.py](backend/app/services/certificates.py). Public API: `generate_credential_id()`, `sign_credential()`, `verify_signature()`, `check_and_issue()`, `safe_check_and_issue()`. Trigger hooks wired into `PATCH /api/progress` (on `done=True` only), `POST /api/repos/link`, and `POST /api/evaluate`. `CERT_HMAC_SECRET` env var added to `config.py` with derivation fallback from `jwt_secret`. Unit tests in [backend/tests/test_certificates.py](backend/tests/test_certificates.py) cover credential format, signature determinism, all four tier gates (capstone, completion, distinction, honors), idempotence, upgrade path, and the no-downgrade invariant.

## Endpoints (planned)

- `GET /api/certificates` — list current user's certificates.
- `GET /api/certificates/{credential_id}/pdf` — stream PDF, increments `pdf_downloads`.
- `GET /verify/{credential_id}` — public HTML verification page with OpenGraph tags.
- `POST /api/certificates/{credential_id}/share-linkedin` — just increments `linkedin_shares`; frontend then opens LinkedIn's feed composer.

Admin:

- `GET /admin/certificates` — all certificates across users.
- `POST /admin/certificates/{credential_id}/revoke` — flip to revoked with reason.

## Issuance engine

Trigger points:

1. **On progress tick** — after `/api/progress` PATCH that sets `done=True`, check if thresholds crossed; issue if yes.
2. **On repo link** — after `/api/repos` POST, same check (repo count might unlock Distinction tier).
3. **On eval complete** — after AI repo evaluation completes, re-check for Honors tier upgrade.

Upgrades: if a user already has a `completion` cert and later hits `distinction`, the tier field updates in place (credential_id and issued_at stay the same — it's a progression, not a new credential).

## LinkedIn share

Uses the feed-composer URL — works without a LinkedIn Company Page:

```
https://www.linkedin.com/sharing/share-offsite/?url=<verification_url>
```

The verification page has Open Graph meta tags so LinkedIn pulls a polished link preview (AutomateEdge logo, learner's course, tier). When/if a Company Page is created, we can layer on the **Add to Profile** API so certs land in LinkedIn's *Licenses & Certifications* section with the logo — Phase 2.

## PDF generation

`weasyprint` (HTML/CSS → PDF). Template at `backend/app/templates/certificate.html`. Fraunces serif + amber brand, embedded QR linking to the verification URL.

## Security

- HMAC secret in `CERT_HMAC_SECRET` env var (falls back to a derived value if unset — deploy should set it).
- Public verification page strips the learner's email (display name only).
- Rate limit on verification views: 60 per IP per hour to prevent scraping.
