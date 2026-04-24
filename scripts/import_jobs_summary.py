"""Import Opus-generated summaries from stdin and write to data.summary.

Pairs with scripts.export_jobs_for_summary. Reads a JSON array of
`{id, summary}` objects from stdin (tolerant of markdown code fences and
leading prose — Opus sometimes wraps output), validates each summary via
the existing _validate_summary clamp, stamps _meta.{model, prompt_version,
generated_at}, and writes atomically per job with SQLite-lock retry.

Prints per-batch stats on stderr; exit code 0 if >=1 job updated.

Run:
  cat opus_output.json | python -m scripts.import_jobs_summary --model opus-4.7
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
from pathlib import Path

logger = logging.getLogger("roadmap.jobs.import_summary")

MAX_RETRIES = 4

# Single source of truth: the prompt template file. Keeps the version here
# and in export_jobs_for_summary.py in sync without two places to update.
_PROMPT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "app" / "prompts" / "jobs_summary_claude.txt",
    Path(__file__).resolve().parent.parent / "backend" / "app" / "prompts" / "jobs_summary_claude.txt",
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

# Schema caps documented in jobs_summary_claude.txt. Tracked here so we can
# surface *how often* Opus slips them (the validator silently clamps, which
# hid drift until now). Anything over cap gets clipped, not rejected —
# rejecting would lose the bullet entirely and the clamp was already there.
SCHEMA_CAPS = {
    "chip_label": 24,
    "resp_title": 48,
    "resp_detail": 90,
    "must_have": 100,
    "benefit": 110,
    "watch_out": 110,
}


def _schema_violations(summary: dict) -> dict[str, int]:
    """Count fields over their documented cap — pre-clamp, for telemetry."""
    v = {k: 0 for k in SCHEMA_CAPS}
    for c in summary.get("headline_chips") or []:
        if isinstance(c, dict) and isinstance(c.get("label"), str):
            if len(c["label"]) > SCHEMA_CAPS["chip_label"]:
                v["chip_label"] += 1
    for r in summary.get("responsibilities") or []:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("title"), str) and len(r["title"]) > SCHEMA_CAPS["resp_title"]:
            v["resp_title"] += 1
        if isinstance(r.get("detail"), str) and len(r["detail"]) > SCHEMA_CAPS["resp_detail"]:
            v["resp_detail"] += 1
    for m in summary.get("must_haves") or []:
        if isinstance(m, str) and len(m) > SCHEMA_CAPS["must_have"]:
            v["must_have"] += 1
    for b in summary.get("benefits") or []:
        if isinstance(b, str) and len(b) > SCHEMA_CAPS["benefit"]:
            v["benefit"] += 1
    for w in summary.get("watch_outs") or []:
        if isinstance(w, str) and len(w) > SCHEMA_CAPS["watch_out"]:
            v["watch_out"] += 1
    return v


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


async def _update_one(job_id: int, summary: dict, model: str) -> tuple[str, dict | None, str | None]:
    """Validate, stamp provenance, write. Returns (outcome, clamped, hash).
    The caller uses `clamped` and `hash` to propagate the summary to any
    other Job rows that share the same content hash (cross-source duplicates,
    re-posts), so Opus is only asked once per unique JD.
    """
    import app.db as _db
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError
    from app.models import Job
    from app.services.jobs_enrich import _validate_summary

    clamped = _validate_summary(summary)
    if clamped is None:
        return "rejected_empty", None, None
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
                    return "missing", None, None
                merged = dict(j.data or {})
                merged["summary"] = clamped
                j.data = merged
                job_hash = j.hash
                await db.commit()
            return "updated", clamped, job_hash
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(0.2 * (2 ** attempt) + random.uniform(0, 0.1))
    return "error", None, None


async def _propagate_to_siblings(source_job_id: int, content_hash: str, clamped: dict) -> int:
    """Copy a freshly-generated summary to any other Job sharing the same
    content hash. Skips siblings already on the current prompt version.
    Returns the number of siblings updated.
    """
    import app.db as _db
    from sqlalchemy import select
    from app.models import Job

    if not content_hash:
        return 0
    async with _db.async_session_factory() as db:
        siblings = (await db.execute(
            select(Job).where(Job.hash == content_hash, Job.id != source_job_id)
        )).scalars().all()
        count = 0
        for s in siblings:
            existing = (s.data or {}).get("summary") or {}
            existing_version = (existing.get("_meta") or {}).get("prompt_version")
            if existing_version == CURRENT_PROMPT_VERSION:
                continue
            merged = dict(s.data or {})
            merged["summary"] = clamped
            s.data = merged
            count += 1
        if count:
            await db.commit()
    return count


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="opus-4.7",
                        help="model tag stamped into summary._meta.model")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    from app.logging_redact import install_redacting_filter
    install_redacting_filter()

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
        violations_total = {k: 0 for k in SCHEMA_CAPS}
        propagated_total = 0
        for item in items:
            if not isinstance(item, dict):
                stats["malformed"] = stats.get("malformed", 0) + 1
                continue
            jid = item.get("id")
            summary = item.get("summary")
            if not isinstance(jid, int) or not isinstance(summary, dict):
                stats["malformed"] = stats.get("malformed", 0) + 1
                continue
            # Pre-clamp schema check so we know when Opus drifts.
            for k, n in _schema_violations(summary).items():
                violations_total[k] += n
            try:
                outcome, clamped, job_hash = await _update_one(jid, summary, args.model)
            except Exception as exc:
                logger.warning("update failed for %s: %s", jid, exc)
                outcome, clamped, job_hash = "error", None, None
            stats[outcome] = stats.get(outcome, 0) + 1
            # Fan out to hash-duplicate siblings so cross-source re-posts
            # don't each need their own Opus round.
            if outcome == "updated" and clamped and job_hash:
                try:
                    propagated_total += await _propagate_to_siblings(jid, job_hash, clamped)
                except Exception as exc:
                    logger.warning("propagation failed from %s: %s", jid, exc)
        # Only surface violation counters that actually fired — keeps the
        # log line readable on the common clean-batch case.
        violations_nonzero = {k: v for k, v in violations_total.items() if v}
        if violations_nonzero:
            stats["schema_violations"] = violations_nonzero
        if propagated_total:
            stats["propagated_to_duplicates"] = propagated_total
        stats["prompt_version"] = CURRENT_PROMPT_VERSION
        logger.info("import stats: %s", stats)
        print(json.dumps(stats))
        return 0 if stats.get("updated", 0) > 0 else 1
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
