# Getting Started with Claude Code

A one-pager for kicking off development on this project with Claude Code. Read this once, then you're in Claude Code's hands.

## 1. Clone the starter into your VPS (or local dev machine)

```bash
# On your VPS or laptop
mkdir -p ~/projects && cd ~/projects
# Unpack the starter kit into a new directory
mkdir ai-roadmap-platform && cd ai-roadmap-platform
# (Copy all files from the starter/ tree into here)

# Initialize git
git init
git add .
git commit -m "Initial scaffolding from starter kit"
```

## 2. Configure your local `.env`

```bash
cp .env.example .env
# Edit .env — at minimum, set JWT_SECRET:
#   openssl rand -hex 32
# Leave the OAuth/SMTP/API keys as placeholders for now; we'll fill them in as phases need them.
```

## 3. Open the folder in VS Code

```bash
code .
```

Install these extensions (VS Code will prompt you if `.vscode/extensions.json` is present — it isn't yet, but these are the ones to grab):

- **Claude** (Anthropic) — the Claude Code integration
- **Python** (Microsoft)
- **Ruff** (Astral) — linter
- **Docker** (Microsoft)
- **YAML** (Red Hat)

## 4. Start Claude Code and orient it

Open the Claude Code panel in VS Code and start a new session. Your very first message should be exactly this:

> Read `CLAUDE.md` first. Then read `docs/TASKS.md` and tell me what Phase 1 Task 1.1 requires. Do not start coding yet — just confirm you understand the state of the project and what the next task is.

Claude Code will read the project memory, understand the phased plan, and confirm it's ready. From there you can say:

> Go ahead with Phase 1, Tasks 1.1 through 1.5. Stop after each task to show me what you changed. Use the test-as-you-go approach.

## 5. Running the stack while Claude Code works

In a terminal:

```bash
docker compose up -d --build
docker compose logs -f backend
```

Leave the logs tailing while Claude Code makes changes. When it asks you to rebuild, run:

```bash
docker compose up -d --build backend
```

## 6. The working loop

This is the rhythm for every session after the first:

1. Start a new Claude Code session
2. First message: **"Read `CLAUDE.md` and `docs/HANDOFF.md`. Tell me where we left off and what the next task is."**
3. Claude confirms, then you direct: **"Proceed with Task X.Y. Stop to show me diffs after."**
4. Review the diffs before committing. Test locally. Ask Claude to explain anything unclear.
5. Commit in small, labeled chunks: `git commit -m "feat(auth): add google oauth callback (#3.3)"`
6. Before ending the session, tell Claude: **"Update `docs/HANDOFF.md` with what we did this session and what's next. Then we're done."**
7. Commit the updated handoff doc.

## 7. What Claude Code will expect you to do manually

A few things Claude Code can't or shouldn't do for you:

- **Create the Google OAuth credentials** in Google Cloud Console (Phase 3.3 — you do this once)
- **Get the Gemini and Groq API keys** from their consoles (Phase 7.2, 7.3)
- **Configure SMTP** with a free email provider (Phase 3.4)
- **Point your reverse proxy** at `127.0.0.1:8080` (Phase 12.3)
- **Review pull requests / diffs** before committing — Claude Code can propose, you approve
- **Approve any new dependencies** Claude Code asks to add

## 8. Rules to give Claude Code when you start

Paste this verbatim into your first session after the initial orientation:

> Rules for this project:
> 1. Never commit secrets. Always check the diff for anything that looks like a key before `git commit`.
> 2. Never add a new dependency without asking me first.
> 3. Small changes. One task at a time. Stop after each task and show me the diff.
> 4. Write tests for non-trivial logic. Skip tests for CSS tweaks.
> 5. Update `docs/HANDOFF.md` at the end of every session.
> 6. If a spec is ambiguous, propose an interpretation, then update the spec doc — don't silently choose.
> 7. If you hit a real blocker, stop and ask me. Don't invent a workaround that isn't in the specs.

## 9. The first session's endpoint

By the end of your first working session, you should have:

- The Docker stack running locally
- `curl http://localhost:8080/api/health` returning 200
- `curl http://localhost:8080/api/learner-count` returning `{"count": 0}`
- The frontend loading at `http://localhost:8080` and ticking checkboxes via localStorage
- A clean git log with one commit per task (5 commits for Phase 1)
- `docs/HANDOFF.md` updated with "Phase 1 complete, starting Phase 2 next session"

That's your checkpoint. If you got here, the stack works and you can iterate.

## 10. When things go wrong

Three escape hatches:

1. **`git reset --hard HEAD`** — wipe uncommitted changes, start the task over
2. **`docker compose down && docker compose up -d --build`** — blow away containers and rebuild
3. **Ask Claude Code to explain** — "I don't understand why X. Walk me through it line by line." Don't accept changes you don't understand.

## 11. Scope discipline

The PRD has 14 features. You don't need all of them on day one. The minimum viable launch is:

- Phase 1: stack running
- Phase 2: database
- Phase 3: Google sign-in (skip OTP for v1 if you want faster shipping)
- Phase 4: progress tracking
- Phase 5: plan customization

That's ~8 sessions of focused work and it's already a useful product. Ship that, then add GitHub linking, AI evaluation, and the rest based on what users actually want.

Don't build features nobody asked for yet. Don't polish for a month before shipping. Get the core loop working, get it on a real domain, share it with 5 people, and iterate based on what they say.

---

**One last thing.** This project is structured around documentation-driven development. The docs are the specs, Claude Code is the builder, you are the reviewer. When the docs and the code disagree, fix one or the other before moving on — don't let them drift. That's the single habit that keeps AI-assisted projects healthy.

Good luck. Have fun building it.
