---
title: Building AutomateEdge Solo — A Free, AI-Curated Learning Platform
slug: 01-building-automateedge-solo
author: Manish Kumar
published: 2026-04-13
tags: [build-in-public, ai-learning, curriculum, certificates, leaderboard]
og_description: Why AutomateEdge exists, what it does for learners, and what I'd do differently. An honest take from a solo builder on curating AI learning that stays current, stays free, and treats the learner's time like it matters.
---

# Building AutomateEdge Solo

A free, self-paced platform that gives anyone a personalised,
AI-curated study plan to learn modern AI from scratch — then tracks
their progress, grades their practice work, and hands them a
verifiable certificate when they finish.

This is the honest story. Why I built it, what it actually does
today, what I got wrong along the way, and where it's going next.

## Why this exists

The AI learning content that already exists falls into two buckets.

Static roadmaps are one-size-fits-all and drift within a quarter.
The thing at the top of "you should learn this first" is rarely the
right starting point six months later. Nobody maintains them.

Paid cohort programs solve the currency problem but gate on price
and schedule. If you work a full-time job and live in a timezone
where the live sessions fall at 2 AM, you're not the target.

AutomateEdge sits between them. The curriculum is curated from
trending signals — university course catalogues, practitioner
writing, current research themes — and re-evaluated every quarter.
It's free. Learners enrol, get a plan tailored to their duration,
level, and career goal, link their practice work as they build,
and graduate with a signed credential they can show a recruiter.

## What it does for a learner

You pick a duration (3, 6, or 12 months) and a level (beginner,
intermediate, advanced). You get a week-by-week plan with focus
areas, deliverables, curated resources split into video courses
and docs/practice, and a checklist per week.

You can link your GitHub repos to the weeks they match. An AI
mentor can answer questions scoped to what you're working on
right now — it sees the current week's focus areas, not the whole
internet. If you've told the platform you're targeting a security
engineer role, the mentor anchors its examples there instead of
a generic data-science framing.

When you cross 90% completion with the capstone month at 100%,
you earn a Completion certificate. Finish everything and link
enough repos and it upgrades to Distinction. Ship something an
automated evaluator scores 8/10 or higher and it upgrades again
to Honors. Each upgrade preserves your original credential ID
and issue date — it's a progression, not a reissue.

## The curriculum stays current by policy, not magic

Quarterly refresh runs an AI discovery pass that proposes
additions and retirements against the previous cycle. The
output feeds a quality pipeline — **generate → review → refine
→ validate → score** — that grades every candidate template
across fifteen dimensions: cognitive progression, theory/practice
ratio, project density, assessment quality, freshness,
prerequisites, real-world readiness, and others.

A template that scores well becomes *publishable*, not
*published*. An admin still has to click Publish. That click
stamps who reviewed it and when, and that stamp is visible to
learners. It's a small thing that makes the difference between
"some algorithm decided this was good" and "a human vouched
for this on this date". The score is a filter, not a judge.

I shipped auto-publish at first. Within two days, a
confidently-wrong template had gone live. I pulled it, added
the human gate, wrote a rule in my notebook: *every
generation pipeline gets a human button, even if the button
does nothing but exist*.

## The certificate actually means something (a little)

Most platform certificates are lipstick on a spreadsheet. A
recruiter can't tell the difference between one you earned
and one you forged in Canva.

AutomateEdge certificates are signed and verifiable. Every
credential ID has a cryptographic signature baked into it.
Anyone with the ID can visit a public verification page and
see a green "Credential verified" badge — or a red one, if
the signature doesn't match. If someone writes a fake ID on
their resume, the verify page will say so.

The page also shows the learner's display name (snapshotted
at the moment of issue, so editing your profile name later
doesn't retroactively change an issued certificate), the
course title, the module breakdown, completion stats, and
the issue date. It's designed to be the thing a recruiter
sees in 20 seconds and either believes or doesn't.

Am I calling this a real industry credential? No. It's a
portfolio proof with tamper detection, and I'm honest about
that distinction. The long-term play is to position
AutomateEdge courses as *preparation for* recognised certs
(DeepLearning.AI specialisations, etc.) and let the existing
trust do the heavy lifting.

## The leaderboard is the most motivating page on the site

It started as a "maybe some people want to see a ranking"
idea and turned out to be the highest-engagement page I
have.

Learners are ranked by XP, which is earned from real
activity: checklist tasks, GitHub repos shipped, certificates
earned (weighted by tier), and active weekly streaks. There
are seven tiers — Apprentice, Learner, Practitioner,
Builder, Engineer, Architect, AI Guru — each with its own
coloured chip and a mini progress bar showing how close you
are to the next one. Achievement pills decorate the page for
milestones like First Task, Triple Crown (three certs),
10-week Hot Streak.

Two rules keep it honest. **Distinct repos, not repo-links** —
linking the same repo to five weeks doesn't earn you 5× the
XP, so you can't farm. **Every number is a live query** —
there's no placeholder data, no fake users, no editorial
curation. If the page says you're Top 5%, the arithmetic
agrees.

There's also a help panel on the leaderboard that spells out
exactly how every signal maps to XP, what each tier requires,
and what triggers each badge. No mystery meat — if you want to
climb, the rules are published.

## What I got wrong

**The auto-publish decision, covered above.** If a generation
pipeline ever lands code that ships to users without a human
button, I have failed the learner.

**Feature breadth before traction.** I built an AI cost
dashboard, batch refinement, a seven-provider fallback chain,
and embedding-based topic dedup before I had more than a
handful of users. The right order was the opposite: get
people on the site, learn what they actually need, build
for that.

**Gut-based provider picks that cost time.** I spent weeks
convinced one specific AI model was the right tool for a
specific task because it had the strongest reputation. The
measurement eventually said a different model was better for
that workload. I had the evidence well before I acted on it.
Lesson: trust the benchmark you ran, not the benchmark you
read.

**Not writing a post-mortem every session.** This is it.
I'm fixing it now.

## What's next

- An admin UI for revoking a credential if a genuine issue
  surfaces.
- Timeframe tabs on the leaderboard (all-time, this month,
  this week) — new learners can climb the monthly ranking
  fast and stay engaged through their first 30 days, which
  is the riskiest window.
- An AI news feed and an AI jobs board. "I finished my
  course, now what?" is the most common question from early
  learners; answering it on-platform is the obvious move.
- More courses beyond the three generalist tracks. The
  quality pipeline is mature enough now that the bottleneck
  is human review capacity, not generation.

## If you're thinking of building something similar

Ship the boring version first. Every layer you don't add is
one you don't have to keep alive.

Build for the user you have, not the user you wish you had.
A free product with ten real learners beats a brilliant
product with zero.

Measure everything that isn't free, and set a hard budget
cap. It's the difference between catching a mistake at a
dollar and discovering it at fifty.

And write the post-mortem at the end of every session, even
if the only reader is tomorrow-you.

---

**Live site:** [automateedge.cloud](https://automateedge.cloud)

**Contact:** Open the footer → Contact. I read everything.
