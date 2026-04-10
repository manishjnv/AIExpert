"""
Quarterly curriculum sync — fetches sources, diffs, generates AI proposal.

Runs once per quarter (via the scheduler container) to:
  1. Fetch content from a curated list of sources (university course pages,
     newsletters, arXiv-sanity, etc.)
  2. Load current curriculum topics for context
  3. Ask Gemini to propose updates (new topics, revisions, retirements)
  4. Write a markdown proposal file under /proposals/
  5. Insert a row into the curriculum_proposals table for the admin panel

The maintainer reviews, edits, and applies the proposal manually — this script
never mutates the published curriculum directly.

Run manually for testing:
  docker compose exec backend python -m scripts.quarterly_sync
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("quarterly_sync")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Curated list of sources
SOURCES: list[dict] = [
    {"name": "Stanford CS229", "url": "https://cs229.stanford.edu/syllabus-summer2024.html", "type": "syllabus"},
    {"name": "Stanford CS224n", "url": "https://web.stanford.edu/class/cs224n/", "type": "syllabus"},
    {"name": "Stanford CS231n", "url": "https://cs231n.github.io/", "type": "syllabus"},
    {"name": "CMU 10-601", "url": "https://www.cs.cmu.edu/~mgormley/courses/10601/", "type": "syllabus"},
    {"name": "MIT 6.S191", "url": "http://introtodeeplearning.com/", "type": "syllabus"},
    {"name": "fast.ai", "url": "https://course.fast.ai/", "type": "syllabus"},
    {"name": "Papers With Code", "url": "https://paperswithcode.com/", "type": "trending"},
]

PROPOSALS_DIR = Path("/proposals")
SNAPSHOT_FILE = Path("/data/last-sync.json")
PROMPT_PATH = Path(__file__).parent.parent / "backend" / "app" / "prompts" / "quarterly_sync.txt"
# Fallback path when running inside the backend container
PROMPT_PATH_ALT = Path("/app/app/prompts/quarterly_sync.txt")
TEMPLATES_DIR = Path("/app/app/curriculum/templates")
TEMPLATES_DIR_LOCAL = Path(__file__).parent.parent / "backend" / "app" / "curriculum" / "templates"


async def fetch_source(source: dict) -> str:
    """Fetch a single source and return extracted text (truncated)."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                source["url"],
                headers={"User-Agent": "AIRoadmap-CurriculumSync/1.0"},
            )
            if resp.status_code != 200:
                logger.warning("Failed to fetch %s: HTTP %d", source["name"], resp.status_code)
                return f"[Failed to fetch {source['name']}: HTTP {resp.status_code}]"

            # Simple text extraction — strip HTML tags
            text = resp.text
            # Remove script/style blocks
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            # Truncate to ~2000 chars per source
            text = text[:2000]

            return f"### {source['name']} ({source['type']})\n{text}"

    except Exception as e:
        logger.warning("Error fetching %s: %s", source["name"], e)
        return f"[Error fetching {source['name']}: {e}]"


async def load_current_topics() -> str:
    """Load the current plan's topic list from template files."""
    tdir = TEMPLATES_DIR if TEMPLATES_DIR.exists() else TEMPLATES_DIR_LOCAL
    if not tdir.exists():
        return "[No templates found]"

    topics = []
    for p in sorted(tdir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            topics.append(f"## {data.get('title', p.stem)}")
            for month in data.get("months", []):
                for week in month.get("weeks", []):
                    topics.append(f"- Week {week['n']}: {week['t']}")
                    topics.extend(f"  - {f}" for f in week.get("focus", []))
        except Exception:
            continue

    return "\n".join(topics) if topics else "[No topics found]"


async def ask_gemini_for_proposal(current_topics: str, recent_content: str) -> str:
    """Call Gemini with the quarterly_sync prompt and return markdown proposal."""
    prompt_path = PROMPT_PATH_ALT if PROMPT_PATH_ALT.exists() else PROMPT_PATH
    if not prompt_path.exists():
        logger.error("Prompt template not found at %s or %s", PROMPT_PATH, PROMPT_PATH_ALT)
        return _fallback_proposal("Prompt template not found")

    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        current_topics=current_topics[:4000],
        recent_content=recent_content[:8000],
    )

    # Try to use the app's AI provider
    try:
        # Add app to path if needed
        sys.path.insert(0, "/app")
        from app.ai.provider import complete
        result, model = await complete(prompt, json_response=False)
        if isinstance(result, str):
            return result
        return str(result)
    except Exception as e:
        logger.warning("AI provider failed: %s. Using fallback.", e)
        return _fallback_proposal(str(e))


def _fallback_proposal(reason: str) -> str:
    """Generate a minimal proposal when AI is unavailable."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"# Curriculum Sync Proposal — {date}\n\n"
        f"**Note:** AI-generated analysis unavailable ({reason}).\n"
        f"Sources were fetched successfully. Manual review recommended.\n\n"
        f"## Action required\n\n"
        f"Review the fetched source content manually and update curriculum as needed.\n"
    )


async def write_proposal(proposal_md: str) -> Path:
    """Write the proposal markdown to /proposals/YYYY-MM-DD-proposal.md."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = PROPOSALS_DIR / f"{date}-proposal.md"
    path.write_text(proposal_md, encoding="utf-8")
    logger.info("Wrote proposal to %s", path)
    return path


async def record_proposal_in_db(proposal_md: str, run_id: str) -> None:
    """Insert a curriculum_proposals row so the admin panel sees the new proposal."""
    try:
        sys.path.insert(0, "/app")
        from app.db import init_db, close_db
        import app.db as db_module
        from app.models.curriculum import CurriculumProposal

        await init_db()
        async with db_module.async_session_factory() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            proposal = CurriculumProposal(
                source_run=run_id,
                proposal_md=proposal_md,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            db.add(proposal)
            await db.commit()
            logger.info("Recorded proposal in DB (run_id=%s)", run_id)
        await close_db()
    except Exception as e:
        logger.error("Failed to record proposal in DB: %s", e)


async def save_snapshot(contents: list[str]) -> None:
    """Save fetched content as a snapshot for future diffs."""
    try:
        SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sources": contents,
        }
        SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save snapshot: %s", e)


async def main() -> int:
    """Entrypoint. Returns 0 on success, non-zero on failure."""
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("Starting quarterly sync run %s", run_id)

    try:
        # 1. Fetch sources in parallel
        fetch_tasks = [fetch_source(s) for s in SOURCES]
        contents = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        successful = [c for c in contents if isinstance(c, str)]
        logger.info("Fetched %d/%d sources successfully", len(successful), len(SOURCES))

        if not successful:
            logger.error("No sources fetched successfully; aborting")
            return 1

        # 2. Save snapshot
        await save_snapshot(successful)

        # 3. Load current topics for context
        current = await load_current_topics()

        # 4. Ask Gemini for a proposal
        proposal = await ask_gemini_for_proposal(current, "\n\n".join(successful))

        # 5. Write to disk
        path = await write_proposal(proposal)

        # 6. Record in DB
        await record_proposal_in_db(proposal, run_id)

        logger.info("Quarterly sync complete: %s", path)
        return 0

    except Exception as exc:
        logger.exception("Quarterly sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
