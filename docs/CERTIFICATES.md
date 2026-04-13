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
