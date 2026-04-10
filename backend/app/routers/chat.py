"""
Chat router — SSE streaming AI chat scoped to the current week.

POST /api/chat streams tokens via Server-Sent Events.
"""

from __future__ import annotations

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

# Simple in-memory rate limiter: user_id -> list of timestamps
_rate_tracker: dict[int, list[float]] = defaultdict(list)
RATE_LIMIT = 20  # messages per hour


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatBody(BaseModel):
    week_num: int
    message: Optional[str] = None
    messages: Optional[list[ChatMessage]] = None


def _check_rate_limit(user_id: int) -> None:
    """Enforce 20 messages per user per hour."""
    now = time.time()
    cutoff = now - 3600
    timestamps = _rate_tracker[user_id]
    # Prune old entries
    _rate_tracker[user_id] = [t for t in timestamps if t > cutoff]
    if len(_rate_tracker[user_id]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Chat rate limit: 20 messages per hour")
    _rate_tracker[user_id].append(now)


def _build_system_prompt(week_num: int, template_key: str = "generalist_6mo_intermediate") -> str:
    """Build the system prompt with week context."""
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
    )


@router.post("/chat")
async def chat(
    body: ChatBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream AI chat response via SSE."""
    _check_rate_limit(user.id)

    system_prompt = _build_system_prompt(body.week_num)

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
