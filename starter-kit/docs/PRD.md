# Product Requirements Document

Scope: the features the platform must ship with to be considered complete. Each feature has a user story, acceptance criteria, and out-of-scope notes to prevent scope creep.

## F1 — Landing page and anonymous browsing

**Story:** A curious visitor lands on the site, sees a sample curriculum, and can browse it without signing in.

**Acceptance criteria:**
- Homepage loads in under 1 second on a fresh visit
- The full default 6-month plan is visible without sign-in
- Progress checkboxes save to browser `localStorage` for anonymous visitors
- A clear call-to-action prompts sign-in for cross-device sync
- "Learners so far" counter is visible (public number)

**Out of scope:** No per-visitor personalization for anonymous mode. Anonymous sees the default plan only.

## F2 — Google SSO sign-in

**Story:** A user clicks "Sign in with Google" and lands back on the site signed in, with any anonymous progress migrated to their account.

**Acceptance criteria:**
- Single-click Google OAuth2 flow via Authlib
- On first sign-in, a User row is created with email, name, avatar URL, provider = "google"
- If the user had anonymous progress in localStorage, it is merged into their cloud progress on first sign-in (conflict resolution: user's local wins for weeks not in cloud; cloud wins for weeks in both)
- JWT session cookie is httpOnly, Secure, SameSite=Lax, 30-day expiry
- Sign out clears the cookie server-side and client-side
- Rate limit: 10 sign-in attempts per IP per 15 minutes

**Out of scope:** Google Workspace admin consent flows, service accounts, refresh token rotation beyond default.

## F3 — Email OTP sign-in

**Story:** A user who doesn't want to use Google enters their email, receives a 6-digit code, enters it, and is signed in.

**Acceptance criteria:**
- `POST /api/auth/otp/request` accepts an email, generates a 6-digit numeric code, stores a hashed version in the DB with a 10-minute expiry, sends the code to the email via SMTP
- `POST /api/auth/otp/verify` accepts email + code, validates against the hashed stored code, creates or finds the User, issues JWT cookie on success
- Codes are single-use; successful verification deletes the code
- Failed verification increments an attempt counter; after 5 failed attempts the code is invalidated
- Rate limit on request: 5 per IP per 15 minutes; 3 per email per hour
- Email template is minimal plaintext + inline HTML, branded with the site name
- Same progress-migration behavior as F2

**Out of scope:** Magic links (OTP only for now). SMS OTP.

## F4 — User profile

**Story:** A signed-in user can see and edit basic profile information.

**Acceptance criteria:**
- Profile page shows: name, email, avatar, account created date, current plan, learning goal, experience level, enrolled duration
- Editable fields: display name, avatar (from Google on SSO; uploaded or gravatar fallback on OTP), learning goal (free text, max 200 chars), experience level (beginner/intermediate/advanced), linked GitHub username
- Delete account button with confirmation — removes User row and cascades to all their data
- Export my data button — returns a JSON dump of their progress, submissions, and profile

**Out of scope:** Multi-user organizations, teams, billing.

## F5 — Customize plan topic and duration

**Story:** On first sign-in (or from the profile page), the user picks a learning goal and duration. The platform generates a plan tailored to them.

**Acceptance criteria:**
- Goal options: "Generalist AI engineer", "GenAI app developer", "ML engineer", "Data scientist" (v1 options; extensible)
- Duration options: 3 months (12 weeks), 6 months (24 weeks), 12 months (48 weeks)
- Experience level: beginner (no coding), intermediate (coder, new to AI), advanced (some ML background)
- Plan generation is deterministic from (goal × duration × experience) — same inputs always produce the same plan; driven by a template file per combination
- Plan templates live in `backend/app/curriculum/templates/{goal}_{duration}_{level}.json`
- Users can re-generate a new plan if they change their goal or duration, with a warning that progress on the old plan will be preserved separately (archived, not deleted)

**Out of scope:** Fully LLM-generated bespoke plans. Mid-plan pivoting. Plan sharing.

## F6 — Weekly content and top resources

**Story:** Each week in the plan shows the topic, learning objectives, deliverables, and 3 top resources.

**Acceptance criteria:**
- Each week has: title, hours estimate, focus bullets, deliverables bullets, 3 resources, checklist items
- Resources have: name, URL, type (youtube/course/docs/blog/paper/book), estimated hours
- Each resource opens in a new tab with rel="noopener noreferrer"
- Resources are stored in the plan template file, not user-editable in v1
- Broken link detection: a weekly cron hits each resource URL once per week and flags dead links in the admin panel

**Out of scope:** User-submitted resources. Resource ratings. Paid resources (Udemy paid courses flagged but not hidden).

## F7 — Progress tracking and progress bars

**Story:** A user ticks off checklist items for each week. They see per-week, per-month, and overall progress.

**Acceptance criteria:**
- Clicking a checkbox persists to the server via `PATCH /api/progress` within 800ms of the click (debounced to avoid write spam)
- Offline mode: ticks save to localStorage and sync when connection returns
- Per-week progress bar shows `checked / total` for that week
- Per-month progress bar shows aggregate across the month's weeks
- Overall progress ring in the header shows total %
- Completing all checkboxes in a week marks the week "complete" with a visual highlight
- Completing all weeks triggers a capstone celebration state

**Out of scope:** Time-based reminders, nudges, streaks (nice-to-haves for v2).

## F8 — Link practice to GitHub

**Story:** A user pastes a GitHub repo URL for a week's deliverable. The platform verifies the repo exists and stores the link.

**Acceptance criteria:**
- Each week has a "Link your repo" input accepting a GitHub URL (owner/repo format or full URL)
- On submit, the backend calls `GET https://api.github.com/repos/{owner}/{repo}` (unauthenticated for public repos is fine for v1)
- If the repo returns 200, store the link on the user's progress for that week
- Show the repo's name, default branch, and last commit date as a confirmation chip
- If the repo is 404, show a friendly error
- The repo link is visible on the week card after saving
- Users can replace the link at any time

**Out of scope:** GitHub App install, private repos, webhook integration, multi-repo per week.

## F9 — AI evaluation of GitHub practice work

**Story:** After linking a repo, the user clicks "Evaluate" and receives an AI-generated score and summary of their work.

**Acceptance criteria:**
- `POST /api/evaluate` accepts a week ID; requires the user to have a linked repo on that week
- The backend fetches the repo's README.md, the top 10 files by size under 50 KB each, and the directory tree (via GitHub's contents API)
- Files matching `.env*`, `*secret*`, `*key*`, `*.pem`, `*credentials*` are excluded before sending to the LLM (see SECURITY.md)
- The total payload sent to the LLM is capped at 20 KB of text
- The prompt is loaded from `backend/app/ai/prompts/evaluate.txt` and includes the week's learning objectives for context
- The LLM returns a JSON object: `{ score: 0-100, strengths: [...], improvements: [...], summary: "..." }`
- The response is stored in an `Evaluation` table linked to the week + user + timestamp
- Cooldown: one evaluation per repo per 24 hours per user (to avoid abusing the free AI quota)
- The user sees the score, strengths, improvements, and summary inline on the week card
- They can request a re-evaluation after any new commit (with cooldown)

**Out of scope:** Multi-file deep review (only top-level inspection). Automated tests on the user's code. Plagiarism detection.

## F10 — LinkedIn share for milestones

**Story:** When a user completes a month or the full capstone, they can share a milestone to LinkedIn with one click.

**Acceptance criteria:**
- Share button appears on month completion and capstone completion
- Clicking opens LinkedIn's share-intent URL: `https://www.linkedin.com/sharing/share-offsite/?url={url}`
- The URL is a public page at `/share/{user_id}/{milestone_id}` that renders a branded milestone card with OpenGraph meta tags
- The OG card shows: user's first name, milestone title, the platform name, and a visual (dynamic SVG served at `/share/{user_id}/{milestone_id}/og.svg`)
- The share page is publicly viewable by anyone with the link (no auth required) but contains no private data

**Out of scope:** LinkedIn API posting (requires app review). Twitter/X sharing. Custom share text editing.

## F11 — Auto-updating curriculum

**Story:** Every 3 months, the curriculum refreshes automatically with new topics based on what's trending at top universities and in practitioner communities.

**Acceptance criteria:**
- A Python script at `scripts/quarterly-sync.py` runs via cron on the 1st day of Jan/Apr/Jul/Oct at 02:00 UTC
- The script fetches content from a curated list of sources:
  - Stanford CS229, CS224n, CS231n, CS329S course pages (syllabi)
  - CMU 10-601, 11-747 syllabi
  - MIT 6.S191, 6.S898 syllabi
  - fast.ai course updates
  - The Batch (DeepLearning.AI newsletter)
  - Papers With Code trending
  - arXiv-sanity top of week
- For each source, the script parses new/updated topics since the last sync
- The script sends the gathered material to Gemini with a prompt asking: "What are the 3–5 most important new topics to add to a generalist AI roadmap, what existing topics should be deprecated, and what existing topics need updates?"
- The AI output is saved as `proposals/{date}-proposal.md` in the repo for the maintainer to review
- The maintainer reviews, edits, approves via a merge, and the new plan version is published
- A changelog entry is automatically added to `PLAN_VERSIONS` in the frontend
- Users see the new badges (NEW, REVISED, OUTDATED) as defined in the existing tracker

**Out of scope:** Fully autonomous curriculum updates without review. Real-time curriculum changes (only quarterly).

## F12 — Compare old vs new topics

**Story:** A returning user sees what changed in the curriculum since their last visit.

**Acceptance criteria:**
- Every week card has an `addedIn: "x.y"` field tracking which plan version introduced it
- Weeks updated in a new version have a `revision: { v, note }` field and show a REVISED badge
- Weeks retired in a new version have an `outdated: { since, reason }` field
- Outdated weeks are hidden by default; a toggle in the toolbar reveals them
- A changelog section at the bottom of the page lists every version with its changes
- Users who return after a gap see an "X new topics since your last visit" banner
- The banner is dismissible and appears only once per version per user

**Out of scope:** Per-user custom plan diffs. Email notification of curriculum updates.

## F13 — AI chat assistant

**Story:** A user has a question about a topic or resource. They click a chat icon and ask it. The AI responds using context from the current week.

**Acceptance criteria:**
- A floating chat button in the bottom-right opens a chat panel
- The chat is scoped to the week the user is viewing (week title + focus + resources are sent as system context)
- Messages go to `POST /api/chat` which forwards to the Gemini API
- Responses are streamed to the user in real time (Server-Sent Events)
- Conversation history is kept in memory client-side only (not persisted in v1)
- Rate limit: 20 messages per user per hour (protect the free Gemini quota)
- The prompt lives at `backend/app/ai/prompts/chat.txt` and instructs the model to be concise, cite resources when relevant, and refuse to answer unrelated questions
- Chat is only available to signed-in users

**Out of scope:** Persistent chat history. Chat across multiple weeks simultaneously. Voice input. Image input.

## F14 — Admin panel

**Story:** The maintainer (a super-admin flagged user) can view the learner count, browse users, see per-week completion rates, and review curriculum proposals.

**Acceptance criteria:**
- Admin panel at `/admin/` accessible only to users with `is_admin = True`
- Dashboard: total users, DAU/WAU/MAU, completion rate per week, dead link report, recent sign-ups
- User browser: list, search by email, view progress, soft-delete an account
- Curriculum proposal viewer: shows pending proposals from the quarterly sync script, one-click "apply to draft version", maintainer then edits and publishes manually

**Out of scope:** Multi-admin role hierarchy. Audit logs (v2). Content management for individual weeks via the UI (edit JSON files directly for now).

## Not in scope for v1 (explicitly)

These come up naturally but are deferred:
- Payments or premium tiers
- Mobile native apps
- Notifications (email, push, in-app)
- Social features (friends, leaderboards, comments)
- Gamification (badges, XP, streaks)
- Multi-language support
- Accessibility audit (WCAG AAA — we target AA by default)
- Browser extension
- CLI client
- Anything requiring a GPU
