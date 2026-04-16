"""Import Opus-generated summaries from stdin and write to data.summary.

Pairs with scripts.export_jobs_for_summary. Reads a JSON array of
`{id, summary}` objects from stdin (tolerant of markdown code fences and
leading prose — Opus sometimes wraps output), validates each summary via
the existing _validate_summary clamp, stamps _meta.{model, prompt_version,
generated_at}, and writes atomically per job with SQLite-lock retry.

Prints per-batch stats on stderr; exit code 0 if >=1 job updated.

Run:
  cat opus_output.json | python -m scripts.import_jobs_summary --model opus-4.6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone

logger = logging.getLogger("roadmap.jobs.import_summary")

MAX_RETRIES = 4
CURRENT_PROMPT_VERSION = "2026-04-16.1"


def _tolerant_parse(raw: str) -> list[dict]:
    """Parse Opus output that may be wrapped in code fences or have preamble."""
    s = raw.strip()
    # Strip common code-fence wrappers.
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # Find the first [ or { and parse from there.
    first = min((i for i in (s.find("["), s.find("{")) if i >= 0), default=-1)
    if first > 0:
        s = s[first:]
    parsed = json.loads(s)
    # Accept either a raw array or a {items: [...]} envelope.
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        return parsed["items"]
    if isinstance(parsed, list):
        return parsed
    raise ValueError("expected JSON array or {items:[]}")


async def _update_one(job_id: int, summary: dict, model: str) -> str:
    import app.db as _db
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.models import Job
    from app.services.jobs_enrich import _validate_summary

    clamped = _validate_summary(summary)
    if clamped is None:
        return "rejected_empty"
    # Provenance stamp — lets future selective re-runs target old versions.
    clamped["_meta"] = {
        "model": model,
        "prompt_version": CURRENT_PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with _db.async_session_factory() as db:
                j = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
                if not j:
                    return "missing"
                merged = dict(j.data or {})
                merged["summary"] = clamped
                j.data = merged
                await db.commit()
            return "updated"
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(0.2 * (2 ** attempt) + random.uniform(0, 0.1))
    return "error"


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="opus-4.6",
                        help="model tag stamped into summary._meta.model")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    raw = sys.stdin.read()
    if not raw.strip():
        logger.error("no input on stdin")
        return 2
    try:
        items = _tolerant_parse(raw)
    except Exception as exc:
        logger.error("could not parse input JSON: %s", exc)
        return 2

    from app.db import close_db, init_db
    await init_db()
    try:
        stats: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                stats["malformed"] = stats.get("malformed", 0) + 1
                continue
            jid = item.get("id")
            summary = item.get("summary")
            if not isinstance(jid, int) or not isinstance(summary, dict):
                stats["malformed"] = stats.get("malformed", 0) + 1
                continue
            try:
                outcome = await _update_one(jid, summary, args.model)
            except Exception as exc:
                logger.warning("update failed for %s: %s", jid, exc)
                outcome = "error"
            stats[outcome] = stats.get(outcome, 0) + 1
        logger.info("import stats: %s", stats)
        print(json.dumps(stats))
        return 0 if stats.get("updated", 0) > 0 else 1
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
