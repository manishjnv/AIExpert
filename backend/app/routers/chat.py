"""
Chat router — SSE streaming AI chat scoped to the current week.

POST /api/chat streams tokens via Server-Sent Events.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.curriculum.loader import load_template
from app.db import get_db
from app.models.user import User

router = APIRouter()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "chat.txt"

# Rate limiter backed by a JSON file so the quota survives restarts and
# redeploys. Single-instance backend, so a process-local lock is enough.
# For multi-instance, swap for a Redis / slowapi storage URI.
RATE_LIMIT = 20  # messages per hour
# Persistence is opt-in. In prod, docker-compose sets CHAT_RATE_DIR=/data so
# the quota survives restarts. In tests, the var is unset and the tracker is
# purely in-memory (same semantics as before this hardening).
_RATE_DIR_ENV = os.environ.get("CHAT_RATE_DIR")
_RATE_DIR: Optional[Path] = Path(_RATE_DIR_ENV) if _RATE_DIR_ENV else None
_RATE_FILE: Optional[Path] = (_RATE_DIR / "chat_rate.json") if _RATE_DIR else None
_rate_lock = threading.Lock()
_rate_tracker: dict[str, list[float]] = defaultdict(list)


def _load_rate_tracker() -> None:
    if not _RATE_FILE:
        return
    try:
        if _RATE_FILE.exists():
            raw = json.loads(_RATE_FILE.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if isinstance(v, list):
                    _rate_tracker[str(k)] = [float(t) for t in v]
    except Exception:
        _rate_tracker.clear()


def _persist_rate_tracker() -> None:
    if not _RATE_FILE or not _RATE_DIR:
        return
    try:
        _RATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _RATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(_rate_tracker)), encoding="utf-8")
        os.replace(tmp, _RATE_FILE)
    except Exception:
        pass


_load_rate_tracker()


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatBody(BaseModel):
    week_num: int
    message: Optional[str] = None
    messages: Optional[list[ChatMessage]] = None


def _check_rate_limit(user_id: int | str) -> None:
    """Enforce 20 messages per user per hour. Survives restarts via JSON file."""
    now = time.time()
    cutoff = now - 3600
    key = str(user_id)
    with _rate_lock:
        timestamps = [t for t in _rate_tracker.get(key, []) if t > cutoff]
        if len(timestamps) >= RATE_LIMIT:
            _rate_tracker[key] = timestamps
            _persist_rate_tracker()
            raise HTTPException(status_code=429, detail="Chat rate limit: 20 messages per hour")
        timestamps.append(now)
        _rate_tracker[key] = timestamps
        # Drop idle keys to keep the file small
        for k in list(_rate_tracker.keys()):
            if not _rate_tracker[k] or max(_rate_tracker[k]) <= cutoff:
                _rate_tracker.pop(k, None)
        _persist_rate_tracker()


def _learner_profile_block(user: Optional[User]) -> str:
    """Render a LEARNER PROFILE section for the system prompt when the
    user has set goal/level on /account. Returns an empty string for
    anonymous visitors or users who haven't filled either field."""
    if user is None:
        return ""
    goal = (user.learning_goal or "").strip()
    level = (user.experience_level or "").strip()
    if not goal and not level:
        return ""
    lines = ["LEARNER PROFILE (use to tailor depth + examples — never restate):"]
    if level:
        lines.append(f"- Experience level: {level}")
    if goal:
        lines.append(f"- Stated career goal: {goal}")
    return "\n".join(lines)


def _build_system_prompt(
    week_num: int,
    template_key: str = "generalist_6mo_intermediate",
    user: Optional[User] = None,
) -> str:
    """Build the system prompt with week context + (optional) learner profile."""
    try:
        tpl = load_template(template_key)
        week = tpl.week_by_number(week_num)
    except (FileNotFoundError, Exception):
        week = None

    if week is None:
        return "You are a helpful AI learning mentor. Answer the student's question."

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    resources_text = "\n".join(
        f"- {r.name}: {r.url}" for r in week.resources
    )
    return prompt_template.format(
        week_num=week.n,
        week_title=week.t,
        focus_areas="\n".join(f"- {f}" for f in week.focus),
        deliverables="\n".join(f"- {d}" for d in week.deliv),
        resources=resources_text,
        learner_profile_block=_learner_profile_block(user),
    )


@router.post("/chat")
async def chat(
    body: ChatBody,
    request: Request,
):
    """Stream AI chat response via SSE. Works for both signed-in and anonymous users."""
    # Rate limit by user ID if signed in, otherwise by IP
    from app.auth.jwt import verify_token
    from app.db import get_db as _get_db
    import app.db as db_module

    rate_key = None
    current_user: Optional[User] = None
    token = request.cookies.get("auth_token")
    if token and db_module.async_session_factory:
        async with db_module.async_session_factory() as db:
            current_user = await verify_token(token, db)
            if current_user:
                rate_key = current_user.id
    if rate_key is None:
        rate_key = f"ip:{request.client.host if request.client else 'unknown'}"
    _check_rate_limit(rate_key)

    system_prompt = _build_system_prompt(body.week_num, user=current_user)

    # Build message list
    messages: list[dict] = [{"role": "user", "content": system_prompt}]

    if body.messages:
        for m in body.messages:
            messages.append({"role": m.role, "content": m.content})
    elif body.message:
        messages.append({"role": "user", "content": body.message})
    else:
        raise HTTPException(status_code=400, detail="Provide message or messages")

    from app.ai.stream import stream_complete

    async def event_generator():
        async for chunk in stream_complete(messages):
            # SSE format: data: <text>\n\n
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
