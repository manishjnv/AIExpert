"""Tests for quarterly sync script (Phase 11).

AC: Running produces a proposal file and a DB row.

Note: scripts/ is mounted in the cron container, not the backend container.
These tests add the repo root to sys.path to import the scripts module.
"""

import sys
from pathlib import Path

# scripts/ is mounted at /app/scripts in the container.
# Ensure /app is on sys.path so `from scripts.quarterly_sync import ...` works.
_app_dir = Path("/app")
_repo_root = Path(__file__).resolve().parent.parent.parent
for p in [str(_app_dir), str(_repo_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import tempfile
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_fetch_source_success():
    """fetch_source returns text content."""
    import httpx
    from scripts.quarterly_sync import fetch_source

    mock_resp = httpx.Response(
        200, text="<html><body><h1>CS229</h1><p>Machine Learning</p></body></html>"
    )

    with patch("scripts.quarterly_sync.httpx.AsyncClient") as mock_cls:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        result = await fetch_source(
            {"name": "CS229", "url": "https://example.com", "type": "syllabus"}
        )
        assert "CS229" in result
        assert "Machine Learning" in result


@pytest.mark.asyncio
async def test_fetch_source_failure():
    """fetch_source handles HTTP errors gracefully."""
    import httpx
    from scripts.quarterly_sync import fetch_source

    mock_resp = httpx.Response(404)

    with patch("scripts.quarterly_sync.httpx.AsyncClient") as mock_cls:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        result = await fetch_source(
            {"name": "Bad", "url": "https://example.com/404", "type": "syllabus"}
        )
        assert "Failed" in result


@pytest.mark.asyncio
async def test_write_proposal():
    """write_proposal creates a markdown file."""
    from scripts.quarterly_sync import write_proposal

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("scripts.quarterly_sync.PROPOSALS_DIR", Path(tmpdir)):
            path = await write_proposal("# Test Proposal\n\nContent here.")
            assert path.exists()
            assert path.read_text().startswith("# Test Proposal")


def test_fallback_proposal():
    """Fallback proposal is generated when AI fails."""
    from scripts.quarterly_sync import _fallback_proposal

    result = _fallback_proposal("test error")
    assert "Curriculum Sync Proposal" in result
    assert "test error" in result


@pytest.mark.asyncio
async def test_load_current_topics():
    """load_current_topics extracts week titles from templates."""
    from scripts.quarterly_sync import load_current_topics

    # In the container, templates are at /app/app/curriculum/templates/
    tpl_dir = Path("/app/app/curriculum/templates")
    if not tpl_dir.exists():
        tpl_dir = Path(__file__).resolve().parent.parent / "app" / "curriculum" / "templates"

    with patch("scripts.quarterly_sync.TEMPLATES_DIR", tpl_dir):
        topics = await load_current_topics()
        assert "Week 1" in topics
        assert "Python" in topics
