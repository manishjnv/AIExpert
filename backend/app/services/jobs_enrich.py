"""AI enrichment for raw scraped jobs.

One Gemini Flash call per job, keyed by content hash (cached by ai_cache).
Fails open: on provider failure, ingest uses `_minimal_enrichment` and flags
admin via `admin_notes`.

See docs/JOBS.md §6.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.ai.provider import complete
from app.services.jobs_sources import RawJob

logger = logging.getLogger("roadmap.jobs.enrich")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "jobs_extract.txt"

# Hard cap on JD chars sent to the model — keeps cost bounded (AI efficiency rule #3).
JD_MAX_CHARS = 6000


ALLOWED_DESIGNATION = {
    "ML Engineer", "Research Scientist", "Applied Scientist", "Data Scientist",
    "Data Engineer", "MLOps Engineer", "AI Product Manager", "AI Engineer",
    "Prompt Engineer", "Research Engineer", "Computer Vision Engineer",
    "NLP Engineer", "AI Solutions Architect", "AI Developer Advocate", "Other",
}
ALLOWED_SENIORITY = {"Intern", "Junior", "Mid", "Senior", "Staff", "Principal", "Lead", "Manager", "Director"}
ALLOWED_TOPIC = {"LLM", "CV", "NLP", "RL", "MLOps", "Data Eng", "Research", "Applied ML", "GenAI", "Robotics", "Safety", "Agents", "RAG", "Fine-tuning", "Evals"}
ALLOWED_REMOTE = {"Remote", "Hybrid", "Onsite"}
ALLOWED_JOB_TYPE = {"Full-time", "Part-time", "Contract", "Internship"}
ALLOWED_SHIFT = {"Day", "Night", "Flexible", "Unknown"}
ALLOWED_TONE = {"primary", "success", "warning", "info", "neutral"}


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def _strip_html(s: str) -> str:
    s = re.sub(r"<script\b[^>]*>.*?</script>", "", s, flags=re.I | re.S)
    s = re.sub(r"<style\b[^>]*>.*?</style>", "", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _scrub_pii(html: str) -> str:
    """Remove scripts/iframes/tracking pixels + redact emails + phones from stored JD HTML."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"<iframe\b[^>]*>.*?</iframe>", "", html, flags=re.I | re.S)
    html = re.sub(r"<img[^>]*>", "", html, flags=re.I)
    html = _EMAIL_RE.sub("[redacted]", html)
    html = _PHONE_RE.sub("[redacted]", html)
    return html


async def _get_module_slugs() -> list[str]:
    """Return published curriculum template keys so the prompt can ground
    `roadmap_modules_matched`. Template keys are the public identifiers
    readers see on their plan (e.g. "ai-zero-to-hero-12mo"); tagging a job
    with them lets the match-% UX link jobs → plans. Best-effort — returns
    [] on any loader failure so the enricher still runs.
    """
    try:
        from app.curriculum.loader import list_published
        return sorted(list_published())[:80]
    except Exception as exc:
        logger.warning("could not load published template keys: %s", exc)
        return []


def _clamp_enum(value, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return default


def _clamp_multi(values, allowed: set[str], cap: int) -> list[str]:
    if not isinstance(values, list):
        return []
    out = [v for v in values if isinstance(v, str) and v in allowed]
    return out[:cap]


def _clip(s: Any, cap: int) -> str:
    return (s[:cap] if isinstance(s, str) else "")


def _validate_summary(raw_summary: Any) -> dict[str, Any] | None:
    """Clamp the LLM-produced summary card. Returns None if nothing usable."""
    if not isinstance(raw_summary, dict):
        return None

    chips_raw = raw_summary.get("headline_chips") or []
    chips: list[dict[str, str]] = []
    if isinstance(chips_raw, list):
        for c in chips_raw[:6]:
            if not isinstance(c, dict):
                continue
            label = _clip(c.get("label"), 32)
            if not label:
                continue
            tone = c.get("tone") if isinstance(c.get("tone"), str) else "neutral"
            if tone not in ALLOWED_TONE:
                tone = "neutral"
            chips.append({"label": label, "tone": tone})

    comp = raw_summary.get("comp_snapshot")
    if isinstance(comp, dict):
        comp = {
            "base": _clip(comp.get("base"), 40) or None,
            "bonus": _clip(comp.get("bonus"), 40) or None,
            "equity": _clip(comp.get("equity"), 40) or None,
            "total_est": _clip(comp.get("total_est"), 40) or None,
        }
        if not comp["base"] and not comp["bonus"] and not comp["equity"]:
            comp = None
    else:
        comp = None

    resp_list: list[dict[str, str]] = []
    for item in (raw_summary.get("responsibilities") or [])[:8]:
        if not isinstance(item, dict):
            continue
        title = _clip(item.get("title"), 64)
        if not title:
            continue
        detail = _clip(item.get("detail"), 120)
        resp_list.append({"title": title, "detail": detail})

    def _str_list(key: str, cap_items: int, cap_len: int) -> list[str]:
        out: list[str] = []
        for s in (raw_summary.get(key) or [])[:cap_items]:
            v = _clip(s, cap_len).strip()
            if v:
                out.append(v)
        return out

    must = _str_list("must_haves", 8, 130)
    benefits = _str_list("benefits", 7, 140)
    watch = _str_list("watch_outs", 4, 140)

    # If nothing useful came back, signal fallback to render path.
    if not (chips or comp or resp_list or must or benefits or watch):
        return None

    out = {
        "headline_chips": chips,
        "comp_snapshot": comp,
        "responsibilities": resp_list,
        "must_haves": must,
        "benefits": benefits,
        "watch_outs": watch,
    }
    # Preserve provenance stamp when present (import_jobs_summary writes _meta
    # with {model, prompt_version, generated_at}; Flash enrichment leaves it off).
    if isinstance(raw_summary.get("_meta"), dict):
        m = raw_summary["_meta"]
        out["_meta"] = {
            "model": _clip(m.get("model"), 40) or None,
            "prompt_version": _clip(m.get("prompt_version"), 40) or None,
            "generated_at": _clip(m.get("generated_at"), 40) or None,
        }
    return out


def _validate(raw_resp: dict, raw: RawJob, module_slugs: list[str]) -> dict[str, Any]:
    """Clamp/fallback every field so downstream code never crashes on AI output."""
    loc = raw_resp.get("location") or {}
    emp = raw_resp.get("employment") or {}
    salary = (emp.get("salary") or {}) if isinstance(emp.get("salary"), dict) else {}
    exp = (emp.get("experience_years") or {}) if isinstance(emp.get("experience_years"), dict) else {}

    modules = raw_resp.get("roadmap_modules_matched") or []
    valid_mod = set(module_slugs)
    modules = [m for m in modules if isinstance(m, str) and (not valid_mod or m in valid_mod)][:6]

    desc = raw_resp.get("description_html") or raw["jd_html"]
    desc = _scrub_pii(desc)

    return {
        "title_raw": raw["title_raw"],
        "designation": _clamp_enum(raw_resp.get("designation"), ALLOWED_DESIGNATION, "Other"),
        "seniority": _clamp_enum(raw_resp.get("seniority"), ALLOWED_SENIORITY, "Mid"),
        "topic": _clamp_multi(raw_resp.get("topic"), ALLOWED_TOPIC, 3) or ["Applied ML"],
        "company": {"name": raw["company"], "slug": raw["company_slug"]},
        "location": {
            "country": loc.get("country") if isinstance(loc.get("country"), str) else None,
            "country_name": loc.get("country_name") if isinstance(loc.get("country_name"), str) else None,
            "city": loc.get("city") if isinstance(loc.get("city"), str) else None,
            "remote_policy": _clamp_enum(loc.get("remote_policy"), ALLOWED_REMOTE, "Onsite"),
            "regions_allowed": [r for r in (loc.get("regions_allowed") or []) if isinstance(r, str)][:20],
        },
        "employment": {
            "job_type": _clamp_enum(emp.get("job_type"), ALLOWED_JOB_TYPE, "Full-time"),
            "shift": _clamp_enum(emp.get("shift"), ALLOWED_SHIFT, "Unknown"),
            "experience_years": {
                "min": exp.get("min") if isinstance(exp.get("min"), int) else None,
                "max": exp.get("max") if isinstance(exp.get("max"), int) else None,
            },
            "salary": {
                "min": salary.get("min") if isinstance(salary.get("min"), (int, float)) else None,
                "max": salary.get("max") if isinstance(salary.get("max"), (int, float)) else None,
                "currency": salary.get("currency") if isinstance(salary.get("currency"), str) else None,
                "disclosed": bool(salary.get("disclosed")),
            },
        },
        "description_html": desc[:40000],
        "tldr": (raw_resp.get("tldr") or "")[:400],
        "must_have_skills": [s for s in (raw_resp.get("must_have_skills") or []) if isinstance(s, str)][:8],
        "nice_to_have_skills": [s for s in (raw_resp.get("nice_to_have_skills") or []) if isinstance(s, str)][:5],
        "roadmap_modules_matched": modules,
        "apply_url": raw["source_url"],
        "summary": _validate_summary(raw_resp.get("summary")),
    }


async def enrich_job(raw: RawJob) -> dict[str, Any]:
    """Call the AI provider chain, validate, and return the enriched payload.

    Raises on repeated provider failure — caller (jobs_ingest) catches and
    falls back to `_minimal_enrichment`.
    """
    jd_text = _strip_html(raw["jd_html"])[:JD_MAX_CHARS]
    module_slugs = await _get_module_slugs()

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (prompt
              .replace("{{company}}", raw["company"])
              .replace("{{title_raw}}", raw["title_raw"])
              .replace("{{location_raw}}", raw["location_raw"])
              .replace("{{jd_text}}", jd_text)
              .replace("{{module_slugs}}", ", ".join(module_slugs) if module_slugs else "(none available — return [])"))

    resp, _model = await complete(prompt, json_response=True, task="jobs_enrich")
    if isinstance(resp, str):
        # Provider returned text (shouldn't happen with json_response=True, but guard).
        try:
            resp = json.loads(resp)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"enrichment returned non-JSON: {exc}")

    if not isinstance(resp, dict):
        raise RuntimeError("enrichment returned non-object payload")

    return _validate(resp, raw, module_slugs)
