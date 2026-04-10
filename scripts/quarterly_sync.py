"""
Quarterly curriculum sync — stub for Phase 11 of TASKS.md.

Runs once per quarter (via the scheduler container) to:
  1. Fetch content from a curated list of sources (university course pages,
     newsletters, arXiv-sanity, etc.)
  2. Diff against the last snapshot
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
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("quarterly_sync")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Curated list of sources Claude Code will implement fetchers for in Phase 11
SOURCES: list[dict] = [
    # University course syllabi
    {"name": "Stanford CS229", "url": "https://cs229.stanford.edu/syllabus-summer2024.html", "type": "syllabus"},
    {"name": "Stanford CS224n", "url": "https://web.stanford.edu/class/cs224n/", "type": "syllabus"},
    {"name": "Stanford CS231n", "url": "https://cs231n.github.io/", "type": "syllabus"},
    {"name": "Stanford CS329S", "url": "https://stanford-cs329s.github.io/", "type": "syllabus"},
    {"name": "CMU 10-601", "url": "https://www.cs.cmu.edu/~mgormley/courses/10601/", "type": "syllabus"},
    {"name": "MIT 6.S191", "url": "http://introtodeeplearning.com/", "type": "syllabus"},
    {"name": "fast.ai", "url": "https://course.fast.ai/", "type": "syllabus"},
    # Practitioner sources
    {"name": "The Batch", "url": "https://www.deeplearning.ai/the-batch/", "type": "newsletter"},
    {"name": "Papers With Code — Trending", "url": "https://paperswithcode.com/", "type": "trending"},
    {"name": "arXiv-sanity", "url": "https://arxiv-sanity-lite.com/", "type": "trending"},
]

PROPOSALS_DIR = Path("/proposals")
SNAPSHOT_FILE = Path("/data/last-sync.json")


async def fetch_source(source: dict) -> str:
    """
    Fetch a single source and return its extracted text content.

    Phase 11 TODO:
      - httpx.AsyncClient with 15s timeout, custom User-Agent from settings
      - For syllabi: simple HTML-to-text extraction (trafilatura or bs4 .get_text())
      - For newsletters: fetch the latest 3 posts
      - For trending: fetch the homepage top 20 items
      - Respect robots.txt
      - Cache responses in /data/sync-cache/ to avoid refetching within a week
    """
    logger.info("fetch_source stub: %s", source["name"])
    return f"[stub content for {source['name']}]"


async def ask_gemini_for_proposal(current_topics: str, recent_content: str) -> str:
    """
    Call Gemini with the quarterly_sync.txt prompt and return the markdown proposal.

    Phase 11 TODO:
      - Load prompt from backend/app/ai/prompts/quarterly_sync.txt
      - Use app.ai.provider.complete() with prefer="gemini-pro" for higher quality
      - Parse and validate the response is well-formed markdown
      - Fall back to a minimal "no changes recommended" proposal on LLM errors
    """
    logger.info("ask_gemini_for_proposal stub")
    return (
        "# Curriculum Sync Proposal (STUB)\n\n"
        "Claude Code will implement the real sync logic in Phase 11 of TASKS.md.\n\n"
        "## New topics to add\n\n- (stub)\n\n"
        "## Topics to revise\n\n- (stub)\n\n"
        "## Topics to retire\n\n- (stub)\n\n"
        "## Resource updates\n\n- (stub)\n\n"
        "## Confidence\n\nlow (this is a stub)\n"
    )


async def load_current_topics() -> str:
    """
    Load the current plan's topic list from the active plan template files.

    Phase 11 TODO: read backend/app/curriculum/templates/*.json,
    extract week titles, return as a formatted string.
    """
    return "[stub — current topic list will go here]"


async def write_proposal(proposal_md: str) -> Path:
    """Write the proposal markdown to /proposals/YYYY-MM-DD-proposal.md."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = PROPOSALS_DIR / f"{date}-proposal.md"
    path.write_text(proposal_md, encoding="utf-8")
    logger.info("Wrote proposal to %s", path)
    return path


async def record_proposal_in_db(proposal_md: str, run_id: str) -> None:
    """
    Insert a curriculum_proposals row so the admin panel sees the new proposal.

    Phase 11 TODO:
      - Use app.db.get_session()
      - Insert with status='pending'
      - Handle DB errors (don't crash the sync job; log and continue)
    """
    logger.info("record_proposal_in_db stub (run_id=%s)", run_id)


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

        # 2. Load current topics for context
        current = await load_current_topics()

        # 3. Ask Gemini for a proposal
        proposal = await ask_gemini_for_proposal(current, "\n\n".join(successful))

        # 4. Write to disk
        path = await write_proposal(proposal)

        # 5. Record in DB
        await record_proposal_in_db(proposal, run_id)

        logger.info("Quarterly sync complete: %s", path)
        return 0

    except Exception as exc:
        logger.exception("Quarterly sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
