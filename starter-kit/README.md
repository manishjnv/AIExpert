# AI Roadmap Platform

A self-hosted web platform that generates personalized AI study plans (3 months to 1 year), tracks progress, auto-refreshes the curriculum every quarter from trending sources, and uses free AI APIs to evaluate learners' GitHub practice work.

**Status:** Planning complete, scaffolding in place, implementation in progress.

## What it does

- **Personalized plans.** Pick your goal, duration (3, 6, or 12 months), and prior experience. The platform generates a week-by-week plan.
- **Progress tracking.** Check off tasks. Per-week, per-month, and overall progress bars. Progress syncs across devices once signed in.
- **Two sign-in modes.** Google SSO for one-click login, or email OTP for users who prefer not to use Google.
- **GitHub practice linking.** Each week's deliverable can be linked to a GitHub repo. The platform verifies the repo exists and counts commits.
- **AI evaluation.** Submit a repo for AI review — the platform fetches the README and top files, sends them to a free AI API (Gemini), and returns a score plus an assessment summary.
- **Top resources per topic.** Every week ships with 3 hand-curated resources (YouTube, Coursera, docs, blog posts) with direct links and time estimates.
- **Auto-refreshing curriculum.** A quarterly cron job pulls trending topics from top universities (Stanford, CMU, MIT), practitioner newsletters, and arXiv-sanity, then generates an update proposal the maintainer reviews and applies.
- **Old vs new topic comparison.** Every curriculum version is tracked. Users can see what changed when they resume the plan.
- **Shareable milestones.** One-click LinkedIn share for capstone completion.
- **AI chat assistant.** Ask questions about any topic or resource — answered by the free Gemini API.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), SQLite
- **Auth:** Google OAuth2, email OTP, JWT cookies
- **Frontend:** Vanilla JS (progressive enhancement over a single HTML file)
- **AI:** Google Gemini API (free tier)
- **Deployment:** Docker Compose on a VPS behind an existing reverse proxy

See `docs/ARCHITECTURE.md` for the full picture.

## Quick start (development)

```bash
# 1. Clone and configure
git clone <repo-url> ai-roadmap-platform
cd ai-roadmap-platform
cp .env.example .env
# Edit .env and fill in the required secrets (see SECURITY.md)

# 2. Bring up the stack
docker compose up -d

# 3. Run migrations
docker compose exec backend alembic upgrade head

# 4. Visit http://localhost:8080
```

## Documentation

| File | Purpose |
|---|---|
| `CLAUDE.md` | Primary context file for Claude Code (read this first if working with an AI coding assistant) |
| `docs/PRD.md` | Product requirements — what each feature does and how it behaves |
| `docs/ARCHITECTURE.md` | Technical architecture and stack rationale |
| `docs/DATA_MODEL.md` | Database schema |
| `docs/API_SPEC.md` | REST API specification |
| `docs/TASKS.md` | Phased build plan with acceptance criteria |
| `docs/SECURITY.md` | Security requirements and threat model |
| `docs/AI_INTEGRATION.md` | Free AI API setup and prompt templates |
| `docs/DEPLOYMENT.md` | VPS deployment workflow |
| `docs/HANDOFF.md` | Living session state, updated after every dev session |

## License

MIT — build on it, fork it, share it.

## A note on AI-assisted development

This project is structured to be built with [Claude Code](https://claude.com/claude-code) or a similar AI coding assistant. The `CLAUDE.md` file and the docs in `/docs/` are written specifically so an AI assistant can read them at the start of a session, understand the state of the project, and pick up where the last session left off. If you're building this manually, the same docs work fine for humans.
