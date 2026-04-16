"""Export a batch of jobs missing data.summary as JSON on stdout.

Designed to be piped over SSH from a Claude Code worker session. The
produced JSON goes into an Opus 4.6 reply; the model's reply is then piped
into scripts.import_jobs_summary to write summaries back.

Selection:
- data.summary is missing OR has _meta.prompt_version != current version
  (so a prompt upgrade auto-surfaces stale summaries for re-gen).
- optional --status filter (draft|published|all)
- prioritises jobs with NO summary (what the admin UI shows as "Missing
  summary") ahead of legacy-summary rows needing a prompt-version refresh,
  then posted_on DESC / id DESC within each tier.

Output shape (one JSON object on stdout):
  {
    "prompt_version": "2026-04-16.1",
    "count": 10,
    "jobs": [
      {"id": 42, "title": "...", "company": "...", "location": "...", "jd_text": "..."},
      ...
    ]
  }

JD text is HTML-stripped + PII-scrubbed + capped at 4000 chars to keep
batches within single-reply output token limits (10 × ~600 tokens = 6K).

Run:
  python -m scripts.export_jobs_for_summary --batch 10 --status draft
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Prompt version lives in the template file (backend/app/prompts/jobs_summary_claude.txt)
# so a version bump is a single edit — no code change needed.
_PROMPT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "app" / "prompts" / "jobs_summary_claude.txt",          # Docker layout
    Path(__file__).resolve().parent.parent / "backend" / "app" / "prompts" / "jobs_summary_claude.txt",  # local repo
]


def _load_prompt_version() -> str:
    for p in _PROMPT_CANDIDATES:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\s*PROMPT_VERSION:\s*(\S+)", line)
                if m:
                    return m.group(1).strip()
    return "unknown"


CURRENT_PROMPT_VERSION = _load_prompt_version()
JD_MAX_CHARS = 4000


def _strip_html(s: str) -> str:
    s = re.sub(r"<script\b[^>]*>.*?</script>", "", s, flags=re.I | re.S)
    s = re.sub(r"<style\b[^>]*>.*?</style>", "", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _needs_regen(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return True
    summary = data.get("summary")
    if not isinstance(summary, dict) or not summary:
        return True
    meta = summary.get("_meta") or {}
    return meta.get("prompt_version") != CURRENT_PROMPT_VERSION


def _missing_summary(data: dict | None) -> bool:
    """True when the admin UI shows this row as 'Missing summary'.
    Matches the admin_jobs filter: $.summary.headline_chips IS NULL.
    """
    if not isinstance(data, dict):
        return True
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return True
    return not summary.get("headline_chips")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=10,
                        help="max jobs per batch (Opus output fits ~10)")
    parser.add_argument("--status", default="draft",
                        help="draft|published|all (default: draft)")
    parser.add_argument("--id", type=int, default=0,
                        help="single-job mode: skip filter, export just this id")
    args = parser.parse_args()

    import app.db as _db
    from sqlalchemy import select
    from app.db import close_db, init_db
    from app.models import Job

    await init_db()
    try:
        async with _db.async_session_factory() as db:
            stmt = select(Job)
            if args.id:
                stmt = stmt.where(Job.id == args.id)
            elif args.status != "all":
                stmt = stmt.where(Job.status == args.status)
            stmt = stmt.order_by(Job.posted_on.desc(), Job.id.desc())
            rows = (await db.execute(stmt)).scalars().all()

        # Missing-summary rows first (what the admin UI counts as "Missing
        # summary"), then legacy-summary rows needing a prompt-version
        # refresh. Python sort is stable, so the SQL ordering
        # (posted_on DESC, id DESC) is preserved within each tier.
        if not args.id:
            rows = sorted(rows, key=lambda r: 0 if _missing_summary(r.data) else 1)

        out: list[dict] = []
        # Hash-dedup within this batch: if two jobs share content hash
        # (re-post, cross-source duplicate), we only ask Opus once and rely
        # on import_jobs_summary to propagate the result to the siblings.
        seen_hashes: set[str] = set()
        for j in rows:
            if not args.id and not _needs_regen(j.data):
                continue
            if not args.id and j.hash:
                if j.hash in seen_hashes:
                    continue
                seen_hashes.add(j.hash)
            d = j.data or {}
            loc = d.get("location") or {}
            loc_str = ", ".join(filter(None, [
                loc.get("city"), loc.get("country_name") or loc.get("country"),
                loc.get("remote_policy"),
            ]))
            jd = _strip_html(d.get("description_html") or "")[:JD_MAX_CHARS]
            out.append({
                "id": j.id,
                "title": j.title,
                "company": (d.get("company") or {}).get("name") or j.company_slug,
                "location": loc_str,
                "jd_text": jd,
            })
            if len(out) >= args.batch:
                break

        sys.stdout.write(json.dumps({
            "prompt_version": CURRENT_PROMPT_VERSION,
            "count": len(out),
            "jobs": out,
        }, ensure_ascii=False))
        sys.stdout.flush()
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
