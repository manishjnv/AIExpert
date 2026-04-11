"""
Template listing endpoint — returns published plan templates only.

Frontend reads this to populate the plan picker dynamically.
Only templates with quality score >= 90 (published) are shown to users.
"""

from fastapi import APIRouter
from app.curriculum.loader import list_published, load_template

router = APIRouter()


@router.get("/templates")
async def get_templates():
    """Return metadata for published plan templates only."""
    keys = list_published()
    templates = []
    for key in sorted(keys):
        try:
            tpl = load_template(key)
            templates.append({
                "key": tpl.key,
                "title": tpl.title,
                "goal": tpl.goal,
                "level": tpl.level,
                "duration_months": tpl.duration_months,
                "total_weeks": tpl.total_weeks,
                "total_checks": tpl.total_checks,
            })
        except Exception:
            continue
    return templates
