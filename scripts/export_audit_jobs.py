"""Export jobs pending Opus audit as a ready-to-run Claude prompt on stdout.

Mirrors GET /admin/jobs/api/audit-pending but runs in-container (no HTTP / no
admin auth) so the auto_audit_jobs.sh weekly cron can pipe it straight to
`claude -p`. The audit prompt template and JD-strip helper live in the admin
router / enrich service and are imported here so the tuned prompt stays a
single source of truth (never duplicated — see CLAUDE.md §8 on prompt assets).

Output (one JSON object on stdout):
  {"count": N, "prompt": "<full prompt incl. jobs JSON>"}

Run:
  python -m scripts.export_audit_jobs
"""

from __future__ import annotations

import asyncio
import json
import sys


async def _main() -> int:
    import app.db as _db
    from sqlalchemy import func, select
    from app.db import close_db, init_db
    from app.models import Job
    from app.routers.admin_jobs import _AUDIT_PROMPT_TEMPLATE
    from app.services.jobs_enrich import _strip_html

    await init_db()
    try:
        async with _db.async_session_factory() as db:
            audit_status = func.json_extract(Job.data, "$.audit.status")
            rows = (await db.execute(
                select(Job).where(audit_status == "pending").order_by(Job.id)
            )).scalars().all()

            # Payload shape MUST match /api/audit-pending so the prompt's
            # current_topic / current_designation keys line up with the
            # template's instructions.
            payload = []
            for j in rows:
                d = j.data or {}
                payload.append({
                    "id": j.id,
                    "title": j.title,
                    "company": j.company_slug,
                    "current_topic": d.get("topic") or [],
                    "current_designation": j.designation,
                    "jd_text": _strip_html(d.get("description_html") or "")[:3000],
                })

        prompt = _AUDIT_PROMPT_TEMPLATE + json.dumps(payload, indent=2, ensure_ascii=False)
        sys.stdout.write(json.dumps({"count": len(payload), "prompt": prompt}, ensure_ascii=False))
        sys.stdout.flush()
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
