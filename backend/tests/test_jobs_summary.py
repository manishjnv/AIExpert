"""Tests for LLM-generated summary: validator clamps + render path."""

from __future__ import annotations

from app.services.jobs_enrich import _validate_summary


def test_validate_summary_clamps_tone_and_caps_items():
    raw = {
        "headline_chips": [
            {"label": "Senior leadership", "tone": "primary"},
            {"label": "NASDAQ: FIGR", "tone": "info"},
            {"label": "Equity (RSUs)", "tone": "success"},
            {"label": "No visa sponsorship", "tone": "warning"},
            {"label": "Forbes top fintech 2025", "tone": "success"},
            {"label": "junk-chip-6", "tone": "neutral"},
            {"label": "junk-chip-7", "tone": "neutral"},
        ],
        "comp_snapshot": {
            "base": "$144-216K", "bonus": "25%", "equity": "RSUs", "total_est": "$180-270K+",
        },
        "responsibilities": [
            {"title": "Salary band design", "detail": "frontline + corporate"},
            {"title": "Job architecture", "detail": "lean framework for rewards"},
        ],
        "must_haves": ["10+ years global comp experience", "C-suite partnership"],
        "benefits": ["100% employer-paid health", "401k", "Up to 12 weeks paid leave"],
        "watch_outs": ["No visa sponsorship", "Pay varies by state"],
    }
    out = _validate_summary(raw)
    assert out is not None
    assert len(out["headline_chips"]) == 6          # capped at 6
    assert all(c["tone"] in {"primary", "success", "warning", "info", "neutral"}
               for c in out["headline_chips"])
    assert out["comp_snapshot"]["base"] == "$144-216K"
    assert out["responsibilities"][0]["title"] == "Salary band design"
    assert len(out["must_haves"]) == 2
    assert "No visa sponsorship" in out["watch_outs"]


def test_validate_summary_rejects_invalid_tone():
    raw = {"headline_chips": [{"label": "X", "tone": "fire"}]}
    out = _validate_summary(raw)
    assert out["headline_chips"][0]["tone"] == "neutral"


def test_validate_summary_drops_empty_comp_snapshot():
    raw = {"comp_snapshot": {"base": None, "bonus": None, "equity": None}}
    out = _validate_summary(raw)
    assert out is None or out.get("comp_snapshot") is None


def test_validate_summary_none_when_nothing_usable():
    assert _validate_summary(None) is None
    assert _validate_summary({}) is None
    assert _validate_summary({"headline_chips": []}) is None


def test_render_summary_card_has_all_sections():
    """Router-level render helper should emit all sections when present."""
    from app.routers.jobs import _render_summary_card
    summary = {
        "headline_chips": [{"label": "Senior", "tone": "primary"}],
        "comp_snapshot": {"base": "$150K", "bonus": None, "equity": "RSUs", "total_est": None},
        "responsibilities": [{"title": "Own X", "detail": "Lead team"}],
        "must_haves": ["10y Python"],
        "benefits": ["Health"],
        "watch_outs": ["No visa"],
    }
    html = _render_summary_card(summary)
    assert "sc-chip sc-primary" in html
    assert "sc-comp" in html and "$150K" in html
    assert "What you&#x27;ll own" in html or "What you&#39;ll own" in html or "What you\u2019ll own" in html or "What you&apos;ll own" in html or "Own X" in html
    assert "Must-haves" in html
    assert "Benefits highlights" in html
    assert "Watch-outs" in html


def test_validate_summary_preserves_meta_stamp():
    """Import script writes _meta{model,prompt_version,generated_at}; clamp must keep it."""
    raw = {
        "must_haves": ["x"],
        "_meta": {
            "model": "opus-4.6",
            "prompt_version": "2026-04-16.1",
            "generated_at": "2026-04-16T09:00:00+00:00",
        },
    }
    out = _validate_summary(raw)
    assert out["_meta"]["model"] == "opus-4.6"
    assert out["_meta"]["prompt_version"] == "2026-04-16.1"
    assert out["_meta"]["generated_at"] == "2026-04-16T09:00:00+00:00"


def test_validate_summary_drops_bogus_meta():
    """Non-dict _meta or missing fields must not crash or leak."""
    raw1 = {"must_haves": ["x"], "_meta": "not-a-dict"}
    out1 = _validate_summary(raw1)
    assert "_meta" not in out1
    raw2 = {"must_haves": ["x"]}
    out2 = _validate_summary(raw2)
    assert "_meta" not in out2


def _import_parse():
    """scripts/ lives at repo root, outside backend/; add to sys.path once."""
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.import_jobs_summary import _tolerant_parse
    return _tolerant_parse


def test_import_script_tolerates_code_fences():
    """Opus sometimes wraps output in ```json ... ```; parser must strip."""
    _tolerant_parse = _import_parse()
    raw = '```json\n[{"id": 1, "summary": {}}]\n```'
    assert _tolerant_parse(raw) == [{"id": 1, "summary": {}}]


def test_import_script_tolerates_leading_prose():
    """Opus sometimes writes 'Here are the summaries:' before the JSON."""
    _tolerant_parse = _import_parse()
    raw = 'Here are the summaries:\n\n[{"id": 2, "summary": {}}]'
    assert _tolerant_parse(raw) == [{"id": 2, "summary": {}}]


def test_import_script_accepts_items_envelope():
    _tolerant_parse = _import_parse()
    raw = '{"items": [{"id": 3, "summary": {}}]}'
    assert _tolerant_parse(raw) == [{"id": 3, "summary": {}}]


def test_render_summary_card_escapes_labels():
    from app.routers.jobs import _render_summary_card
    summary = {"headline_chips": [{"label": "<script>", "tone": "neutral"}], "must_haves": ["x"]}
    html = _render_summary_card(summary)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
