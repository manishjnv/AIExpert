"""Apply Opus audit verdicts from stdin to Job.data.audit. Commits per row.

Pairs with scripts.export_audit_jobs + the auto_audit_jobs.sh weekly cron.
Reads a JSON array of verdicts (tolerant of markdown fences / prose preamble)
and replicates POST /admin/jobs/api/audit-submit: records each verdict on
Job.data.audit and, when agreed=false, prepends an "OPUS-AUDIT mismatch" note
to admin_notes for admin follow-up.

NEVER changes topic / designation / status — a mismatch only *flags* the row
for a human to review and act on. Keep the verdict shape + update logic in sync
with admin_jobs.submit_audit_results (the source of truth).

Commits per row (not one big transaction) per the SQLite-WAL writer rule
(feedback_sqlite_writer_sessions) — the cron runs while the live backend may
hold the writer slot.

Prints stats JSON on stdout; exit 0 if >=1 row updated, else 1.

Run:
  cat verdicts.json | python -m scripts.import_audit_results
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import datetime

logger = logging.getLogger("roadmap.jobs.import_audit")


def _parse_array(raw: str) -> list:
    """Tolerant parse: strip code fences / prose preamble, then JSON-load."""
    s = raw.strip()
    s = re.sub(r"^`{1,3}(?:json)?\s*", "", s)
    s = re.sub(r"\s*`{1,3}\s*$", "", s)
    idx = s.find("[")
    if idx > 0:
        s = s[idx:]
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of verdicts")
    return data


async def _main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    raw = sys.stdin.read()
    try:
        results = _parse_array(raw)
    except Exception as exc:
        print(json.dumps({"error": f"parse failed: {exc}"}))
        return 1

    import app.db as _db
    from sqlalchemy import select
    from app.db import close_db, init_db
    from app.models import Job

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    updated = mismatches = skipped = 0

    await init_db()
    try:
        for r in results:
            if not isinstance(r, dict) or "job_id" not in r:
                skipped += 1
                continue
            try:
                jid = int(r["job_id"])
            except (TypeError, ValueError):
                skipped += 1
                continue

            # Fresh session + commit per row (WAL writer rule).
            async with _db.async_session_factory() as db:
                job = (await db.execute(select(Job).where(Job.id == jid))).scalar_one_or_none()
                if job is None:
                    skipped += 1
                    continue

                agreed = bool(r.get("agreed"))
                opus_topic = r.get("opus_topic") if isinstance(r.get("opus_topic"), list) else []
                opus_des = r.get("opus_designation") if isinstance(r.get("opus_designation"), str) else None
                notes = (r.get("notes") or "").strip()[:300]

                new_data = dict(job.data or {})
                prior = new_data.get("audit") or {}
                new_data["audit"] = {
                    "selected_at": prior.get("selected_at"),
                    "reviewed_at": now_iso,
                    "status": "reviewed",
                    "agreed": agreed,
                    "opus_topic": opus_topic,
                    "opus_designation": opus_des,
                    "notes": notes,
                }
                job.data = new_data  # reassign so SQLAlchemy tracks the JSON change

                if not agreed:
                    mismatches += 1
                    stamp = f"OPUS-AUDIT mismatch ({now_iso[:10]}): {notes or 'no notes'}"
                    existing = (job.admin_notes or "").strip()
                    job.admin_notes = f"{stamp} | {existing}".rstrip(" |") if existing else stamp

                await db.commit()
                updated += 1
    finally:
        await close_db()

    stats = {"updated": updated, "mismatches": mismatches, "skipped": skipped}
    print(json.dumps(stats))
    logger.info("audit import stats: %s", stats)
    return 0 if updated else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
