"""Tests for Phase 14 cost optimizations (pre-filter, JD cap, prompt split,
summary removal, tier enrichment).

Covers:
  - Opt #4: Non-AI title pre-filter (is_non_ai_title + ingest integration)
  - Opt #7: JD_MAX_CHARS reduced to 4000
  - Opt #1: system_instruction passed through provider to Gemini
  - Opt #5: Flash prompt has no summary schema; summary=None in output
  - Opt #3: Tier-2 lightweight enrichment (enrich_job_lite)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

import app.db as db_module
from app.db import Base, close_db, init_db
from app.models import Job, JobCompany
from app.services import jobs_ingest
from app.services.jobs_sources import RawJob


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _raw(**over) -> RawJob:
    base = RawJob(
        external_id="gh-1",
        source_url="https://boards.greenhouse.io/anthropic/jobs/1",
        title_raw="Senior ML Engineer",
        company="Anthropic",
        company_slug="anthropic",
        location_raw="San Francisco, CA",
        jd_html="<p>Build LLMs at scale. Must have PyTorch.</p>",
        posted_on="2026-04-10",
        extra={},
    )
    base.update(over)  # type: ignore[call-arg]
    return base


def _fake_enrich(raw: RawJob) -> dict:
    return {
        "title_raw": raw["title_raw"],
        "designation": "ML Engineer",
        "seniority": "Senior",
        "topic": ["LLM"],
        "company": {"name": raw["company"], "slug": raw["company_slug"]},
        "location": {"country": "US", "city": "San Francisco", "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 5, "max": 8},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "description_html": raw["jd_html"],
        "tldr": "Rewrite of the JD.",
        "must_have_skills": ["PyTorch"],
        "nice_to_have_skills": [],
        "roadmap_modules_matched": [],
        "apply_url": raw["source_url"],
        "summary": None,
    }


# ===================================================================
# Opt #4: Pre-filter non-AI titles
# ===================================================================

class TestNonAITitleFilter:
    """is_non_ai_title should catch obviously non-AI roles."""

    def test_sales_manager(self):
        assert jobs_ingest.is_non_ai_title("Sales Manager, Enterprise") is True

    def test_recruiter(self):
        assert jobs_ingest.is_non_ai_title("Senior Technical Recruiter") is True

    def test_accountant(self):
        assert jobs_ingest.is_non_ai_title("Staff Accountant") is True

    def test_legal_counsel(self):
        assert jobs_ingest.is_non_ai_title("General Counsel") is True

    def test_office_manager(self):
        assert jobs_ingest.is_non_ai_title("Office Manager") is True

    def test_facilities(self):
        assert jobs_ingest.is_non_ai_title("Facilities Coordinator") is True

    def test_hr_business_partner(self):
        assert jobs_ingest.is_non_ai_title("Senior HR Business Partner") is True

    def test_content_writer(self):
        assert jobs_ingest.is_non_ai_title("Content Writer - Blog") is True

    def test_executive_assistant(self):
        assert jobs_ingest.is_non_ai_title("Executive Assistant to CEO") is True

    # ---- Should NOT be filtered ----

    def test_ml_engineer_passes(self):
        assert jobs_ingest.is_non_ai_title("Senior ML Engineer") is False

    def test_research_scientist_passes(self):
        assert jobs_ingest.is_non_ai_title("Research Scientist, LLMs") is False

    def test_data_scientist_passes(self):
        assert jobs_ingest.is_non_ai_title("Data Scientist") is False

    def test_ai_product_manager_passes(self):
        assert jobs_ingest.is_non_ai_title("AI Product Manager") is False

    def test_mlops_passes(self):
        assert jobs_ingest.is_non_ai_title("MLOps Engineer") is False

    def test_prompt_engineer_passes(self):
        assert jobs_ingest.is_non_ai_title("Prompt Engineer") is False

    def test_software_engineer_passes(self):
        """Generic SWE titles should NOT be filtered — they may be AI-adjacent."""
        assert jobs_ingest.is_non_ai_title("Software Engineer, Backend") is False

    def test_case_insensitive(self):
        assert jobs_ingest.is_non_ai_title("SALES MANAGER") is True
        assert jobs_ingest.is_non_ai_title("sales manager") is True

    # ---- RCA-026: legal titles that slipped through ----

    def test_legal_manager(self):
        """PhonePe variant: 'Legal Manager'."""
        assert jobs_ingest.is_non_ai_title("Legal Manager") is True

    def test_manager_comma_legal(self):
        """PhonePe variant: 'Manager, Legal'."""
        assert jobs_ingest.is_non_ai_title("Manager, Legal") is True

    def test_corporate_counsel(self):
        assert jobs_ingest.is_non_ai_title("Senior Corporate Counsel") is True

    def test_compliance_manager(self):
        assert jobs_ingest.is_non_ai_title("Compliance Manager, APAC") is True

    def test_benefits_administration(self):
        """Another PhonePe false-positive from session 14e."""
        assert jobs_ingest.is_non_ai_title("Lead Exit and Benefits Administration") is True

    def test_merchant_kyc(self):
        assert jobs_ingest.is_non_ai_title("Operations Associate, Merchant KYC") is True


class TestNonAIJDSignals:
    """has_non_ai_jd_signals should flag legal/HR/finance JDs with no AI content.

    Mirrors RCA-026: PhonePe 'Manager, Legal' had 'LLB / LLM from a recognized
    university' + 'PQE' + 'Indian Contract Act' + 'procurement contracts' +
    'MSA/NDA' but no AI signal words. The two-gate rule (>=2 non-AI hits AND
    zero AI signals) must catch it.
    """

    def test_phonepe_legal_jd_flagged(self):
        jd = (
            "<p>LLB / LLM from a recognized university. Minimum 7 years of "
            "post-qualification experience in corporate legal practice. "
            "Draft and negotiate procurement contracts, MSAs, NDAs. "
            "Ensure contracts comply with Indian Contract Act.</p>"
        )
        assert jobs_ingest.has_non_ai_jd_signals(jd) is True

    def test_ml_engineer_jd_not_flagged(self):
        """Must NOT flag legit AI jobs that mention contracts/NDAs in passing."""
        jd = (
            "<p>Build large language model systems at scale. "
            "Fine-tuning, PyTorch, and RAG pipelines. "
            "You'll sign a standard NDA before starting.</p>"
        )
        assert jobs_ingest.has_non_ai_jd_signals(jd) is False

    def test_single_legal_term_not_flagged(self):
        """Single non-AI hit is below the >=2 threshold."""
        jd = "<p>Software Engineer role. You'll sign an NDA before starting.</p>"
        assert jobs_ingest.has_non_ai_jd_signals(jd) is False

    def test_generic_swe_jd_not_flagged(self):
        jd = "<p>Backend engineer. Python, FastAPI, PostgreSQL.</p>"
        assert jobs_ingest.has_non_ai_jd_signals(jd) is False

    def test_llm_degree_with_law_firm_flagged(self):
        """LLM-as-degree + law firm keyword = law job, not AI."""
        jd = (
            "<p>We are hiring an associate with LL.M. from a top law school. "
            "Law firm experience preferred. Contract drafting required.</p>"
        )
        assert jobs_ingest.has_non_ai_jd_signals(jd) is True


@pytest.mark.asyncio
async def test_jd_prefilter_skips_enrichment():
    """Legal JD must be staged with admin_notes and no AI call."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m, \
         patch("app.services.jobs_enrich.enrich_job_lite", new_callable=AsyncMock) as ml:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        ml.side_effect = lambda raw, **kw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            r = _raw(
                title_raw="Senior Associate",  # generic title — passes title filter
                jd_html=(
                    "<p>LLB / LLM degree. 7 years PQE in corporate legal practice. "
                    "Draft procurement contracts, MSAs, NDAs. Indian Contract Act.</p>"
                ),
            )
            result = await jobs_ingest._stage_one(r, "greenhouse:phonepe", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "auto-skipped" in (job.admin_notes or "")
            assert "non-AI JD" in (job.admin_notes or "")
            m.assert_not_called()
            ml.assert_not_called()
    await close_db()


# ===================================================================
# Wave 1 #1 — title pattern expansion (21 new "AI-adjacent but not AI" scenarios)
# ===================================================================

class TestWave1TitlePatterns:
    """The 21 'requires AI knowledge but isn't an AI role' scenarios that
    Gemini routinely misclassifies because the JD legitimately mentions
    machine learning / LLMs / AI — but as a job *requirement* for a non-AI
    role. Each pattern represents one of those scenarios."""

    def test_sales_engineer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Sales Engineer, AI Platform") is True

    def test_solutions_engineer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Solutions Engineer - LLM Products") is True

    def test_pre_sales_filtered(self):
        assert jobs_ingest.is_non_ai_title("Pre-Sales Engineer, Enterprise AI") is True

    def test_business_development_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Business Development Manager, AI Tools") is True

    def test_partnerships_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Partnerships Manager, AI APIs") is True

    def test_program_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Program Manager, ML Research") is True

    def test_technical_program_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Technical Program Manager, AI Safety") is True

    def test_chief_of_staff_filtered(self):
        assert jobs_ingest.is_non_ai_title("Chief of Staff, AI Research Team") is True

    def test_product_marketing_filtered(self):
        assert jobs_ingest.is_non_ai_title("Senior Product Marketing Manager, GenAI") is True

    def test_growth_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Growth Manager, AI Products") is True

    def test_policy_analyst_filtered(self):
        assert jobs_ingest.is_non_ai_title("Senior Policy Analyst, AI Governance") is True

    def test_ai_ethicist_filtered(self):
        """An ethicist who studies AI is a policy/ethics role, not an AI builder."""
        assert jobs_ingest.is_non_ai_title("AI Ethicist") is True

    def test_investor_relations_filtered(self):
        assert jobs_ingest.is_non_ai_title("Investor Relations Manager") is True

    def test_revops_filtered(self):
        assert jobs_ingest.is_non_ai_title("Revenue Operations Lead") is True

    def test_community_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Community Manager, Developer AI") is True

    def test_technical_writer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Senior Technical Writer, AI Documentation") is True

    def test_ux_designer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Senior UX Designer, Claude Mobile") is True

    def test_ux_researcher_filtered(self):
        assert jobs_ingest.is_non_ai_title("UX Researcher, AI Products") is True

    def test_appsec_filtered(self):
        assert jobs_ingest.is_non_ai_title("Application Security Engineer") is True

    def test_infosec_filtered(self):
        assert jobs_ingest.is_non_ai_title("InfoSec Analyst") is True

    def test_help_desk_filtered(self):
        assert jobs_ingest.is_non_ai_title("Help Desk Technician") is True

    def test_video_producer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Senior Video Producer, AI Storytelling") is True

    def test_clinical_reviewer_filtered(self):
        assert jobs_ingest.is_non_ai_title("Clinical Reviewer, Medical AI") is True

    def test_localization_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Localization Manager, Claude") is True

    def test_vendor_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Strategic Sourcing Manager") is True

    def test_customer_solutions_architect_filtered(self):
        """Sales-side 'CSA' is post-sales, not engineering."""
        assert jobs_ingest.is_non_ai_title("Customer Solutions Architect, Enterprise") is True

    def test_technical_account_manager_filtered(self):
        assert jobs_ingest.is_non_ai_title("Technical Account Manager, AI APIs") is True

    # ---- Must NOT be filtered (regression guards) ----

    def test_ml_engineer_passes(self):
        assert jobs_ingest.is_non_ai_title("Senior ML Engineer, Inference") is False

    def test_research_scientist_passes(self):
        assert jobs_ingest.is_non_ai_title("Research Scientist, Reinforcement Learning") is False

    def test_ai_solutions_architect_passes(self):
        """Different from sales-side 'Customer Solutions Architect' — AI SA is whitelisted."""
        assert jobs_ingest.is_non_ai_title("AI Solutions Architect") is False

    def test_ai_developer_advocate_passes(self):
        """Whitelisted designation; do NOT filter."""
        assert jobs_ingest.is_non_ai_title("AI Developer Advocate") is False

    def test_prompt_engineer_passes(self):
        assert jobs_ingest.is_non_ai_title("Prompt Engineer") is False

    def test_applied_scientist_passes(self):
        assert jobs_ingest.is_non_ai_title("Applied Scientist, NLP") is False


# ===================================================================
# Wave 1 #2 — designation↔topic consistency
# ===================================================================

class TestDesignationTopicConsistency:
    """designation=='Other' must force topic=[]; AI-adjacent designations
    capped at 1 topic. Catches Gemini self-contradictions where it labels a
    role 'Other' but still assigns AI topics."""

    def test_other_designation_forces_empty_topic(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("Other", ["Applied ML", "LLM"]) == []

    def test_ml_engineer_designation_keeps_topics(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("ML Engineer", ["Applied ML", "LLM"]) == ["Applied ML", "LLM"]

    def test_ai_product_manager_capped_to_one(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("AI Product Manager", ["Applied ML", "LLM", "GenAI"]) == ["Applied ML"]

    def test_ai_solutions_architect_capped_to_one(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("AI Solutions Architect", ["LLM", "RAG"]) == ["LLM"]

    def test_ai_developer_advocate_capped_to_one(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("AI Developer Advocate", ["LLM", "GenAI", "Agents"]) == ["LLM"]

    def test_research_scientist_keeps_all(self):
        from app.services.jobs_enrich import _enforce_designation_topic_consistency
        assert _enforce_designation_topic_consistency("Research Scientist", ["RL", "Research", "Safety"]) == ["RL", "Research", "Safety"]


# ===================================================================
# Wave 2 #6–#10 — AI-intensity scoring (word-boundary regex, 3-tier
# scoring with per-JD dedup, company boilerplate stripped before scoring)
# ===================================================================

class TestAIIntensityScoring:
    """compute_ai_intensity returns a weighted score: STRONG x3 + MEDIUM x2
    + WEAK x1, each pattern counted once per JD. Threshold = 5."""

    def test_strong_alone_scores_3(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Build deep learning models") == 3

    def test_two_distinct_strongs_sum(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Use PyTorch and TensorFlow") == 6

    def test_three_distinct_strongs_sum(self):
        from app.services.jobs_ingest import compute_ai_intensity
        # pytorch + fine-tuning + RLHF = 9
        assert compute_ai_intensity("PyTorch fine-tuning with RLHF") == 9

    def test_medium_alone_scores_2(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Some LLM applications") == 2

    def test_weak_alone_scores_1(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("AI-powered platform") == 1

    def test_strong_plus_medium_passes_threshold(self):
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        # 3 + 2 = 5 == threshold
        assert compute_ai_intensity("Build deep learning. LLM is involved.") >= AI_INTENSITY_THRESHOLD

    def test_one_strong_alone_below_threshold(self):
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        assert compute_ai_intensity("Use PyTorch for some task") < AI_INTENSITY_THRESHOLD

    def test_dedup_repeated_terms(self):
        """Each pattern counts at most once per JD — boilerplate can't inflate."""
        from app.services.jobs_ingest import compute_ai_intensity
        # 5 hits of weak "AI-powered" = 1, not 5
        assert compute_ai_intensity("AI-powered AI-powered AI-powered AI-powered AI-powered") == 1
        # 3 hits of strong "pytorch" = 3, not 9
        assert compute_ai_intensity("PyTorch PyTorch PyTorch") == 3

    def test_substring_noise_not_matched(self):
        """Word-boundary regex avoids the old substring-in noise problem."""
        from app.services.jobs_ingest import compute_ai_intensity
        # "shopping"/"appointment" must not match \bppo\b (not in our list anyway)
        # "fragment" must not match \brag\b
        # "fulfillment" must not match \bllm\b
        # "Albert" must not match \bbert\b (not in list)
        # "jaxon" must not match \bjax\b
        # "ACL" must not match \bacl\b (not in list)
        text = "Shopping carts. Albert. Aggregate fragment data. Fulfillment of orders. Jaxon manages ACLs."
        assert compute_ai_intensity(text) == 0

    def test_word_boundary_llm(self):
        from app.services.jobs_ingest import compute_ai_intensity
        # \bllm\b must match
        assert compute_ai_intensity("Work on LLM applications") == 2
        # \bllm\b must NOT match "fulfillment"
        assert compute_ai_intensity("Order fulfillment specialist") == 0
        # \bllm\b must match "LLM-based" (hyphen is a word boundary)
        assert compute_ai_intensity("LLM-based system") >= 2

    def test_word_boundary_rag(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Build a RAG system") == 2
        # "fragment", "aggregate", "drag" must not match
        assert compute_ai_intensity("Fragment data, drag-drop, aggregate views") == 0

    def test_word_boundary_jax(self):
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Build models in JAX") == 3
        # "Jaxon", "jaxson" must not match
        assert compute_ai_intensity("Hi I am Jaxon") == 0

    def test_qualified_brand_names(self):
        """Bare 'Claude'/'Gemini' must not match — require API/model qualifier."""
        from app.services.jobs_ingest import compute_ai_intensity
        # Bare "Claude" (could be a person's name) — no match
        assert compute_ai_intensity("Met with Claude yesterday") == 0
        # Qualified "Claude Sonnet" — strong
        assert compute_ai_intensity("Use Claude Sonnet for inference") == 3
        # "Claude API" — strong
        assert compute_ai_intensity("Integrate the Claude API") == 3
        # Bare "Gemini" — no match
        assert compute_ai_intensity("Born under Gemini zodiac") == 0
        # "Gemini API" — strong
        assert compute_ai_intensity("Call the Gemini API for completions") == 3

    def test_acl_not_a_signal(self):
        """ACL = access control list. Must NOT count as AI signal."""
        from app.services.jobs_ingest import compute_ai_intensity
        assert compute_ai_intensity("Configure ACLs for the API") == 0

    def test_threshold_constant(self):
        from app.services.jobs_ingest import AI_INTENSITY_THRESHOLD
        assert AI_INTENSITY_THRESHOLD == 5


class TestBoilerplateStripping:
    """Company-mission/about-us paragraphs get stripped before scoring."""

    def test_about_anthropic_section_stripped(self):
        from app.services.jobs_ingest import _strip_company_boilerplate
        jd = ("About Anthropic. Anthropic mission is to create reliable AI. "
              "We work on machine learning, deep learning, and large language models. "
              "About the role. You will manage office facilities and visitor logistics.")
        stripped = _strip_company_boilerplate(jd)
        assert "machine learning" not in stripped.lower()
        assert "office facilities" in stripped.lower()

    def test_our_mission_stripped(self):
        from app.services.jobs_ingest import _strip_company_boilerplate
        jd = ("Our mission is to advance generative AI. About the role. Help with travel arrangements.")
        stripped = _strip_company_boilerplate(jd)
        assert "generative ai" not in stripped.lower()
        assert "travel arrangements" in stripped.lower()

    def test_no_boilerplate_passthrough(self):
        from app.services.jobs_ingest import _strip_company_boilerplate
        jd = "Build PyTorch models and deploy to production."
        assert _strip_company_boilerplate(jd) == jd

    def test_about_openai_section_stripped(self):
        from app.services.jobs_ingest import _strip_company_boilerplate
        jd = ("About OpenAI. We build large language models and AI agents. "
              "Responsibilities. Manage office logistics.")
        stripped = _strip_company_boilerplate(jd)
        assert "large language models" not in stripped.lower()
        assert "office logistics" in stripped.lower()

    def test_real_ai_role_passes_intensity(self):
        """A genuine AI Research role at Anthropic should still pass after boilerplate strip."""
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        jd = ("About Anthropic. Anthropic mission is to create reliable AI. "
              "About the role. You will work on RLHF and reward model training. "
              "Build PyTorch pipelines for fine-tuning large language models. "
              "Requirements: experience with deep learning and machine learning.")
        assert compute_ai_intensity(jd) >= AI_INTENSITY_THRESHOLD

    def test_office_manager_at_ai_lab_doesnt_pass(self):
        """The motivating example: office manager at Anthropic — boilerplate strip
        prevents the AI-lab vocabulary from inflating the role's intensity."""
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        jd = ("About Anthropic. Anthropic builds AI systems with machine learning "
              "and large language models. About the role. Manage office facilities, "
              "vendor coordination, visitor logistics. Requirements: organizational "
              "skills, calendar management, attention to detail.")
        assert compute_ai_intensity(jd) < AI_INTENSITY_THRESHOLD


# ===================================================================
# Wave 3 #11 — non-AI cluster expansion (sales/marketing/design/recruiting/
# IT/creative/policy clusters added to _NON_AI_JD_SIGNALS)
# ===================================================================

class TestNonAIClusterExpansion:
    """Wave 3 #11 added 7 new cluster groups. Verify each catches a
    representative JD that escaped Wave 1+2."""

    def test_sales_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Drive pipeline generation and own quarterly sales quota. "
              "Manage the entire sales cycle and close deals. "
              "Familiarity with AI products is a plus.")
        assert has_non_ai_jd_signals(jd) is True

    def test_marketing_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Own brand voice and content calendar across paid media. "
              "Drive demand generation and measure campaign performance. "
              "Excited about AI-powered marketing.")
        assert has_non_ai_jd_signals(jd) is True

    def test_design_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Own the design system in Figma. Build wireframes and run "
              "user research with usability testing. "
              "Designing for AI-driven products.")
        assert has_non_ai_jd_signals(jd) is True

    def test_recruiting_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Manage the candidate pipeline and offer letter process. "
              "Source candidates through LinkedIn Recruiter. "
              "Familiarity with machine learning concepts.")
        assert has_non_ai_jd_signals(jd) is True

    def test_finance_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Lead month-end close, journal entries, and balance sheet "
              "reconciliation. Ensure GAAP compliance. "
              "Knowledge of AI accounting tools a plus.")
        assert has_non_ai_jd_signals(jd) is True

    def test_it_support_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Manage ticket queue in Zendesk and Jira Service. "
              "Own SLA response times and the escalation path. "
              "AI-powered support tools a plus.")
        assert has_non_ai_jd_signals(jd) is True

    def test_creative_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Edit videos in Adobe Premiere and Final Cut Pro. "
              "Own storyboard development and motion graphics. "
              "Working on AI storytelling.")
        assert has_non_ai_jd_signals(jd) is True

    def test_policy_cluster_flagged(self):
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Draft white papers and policy briefs on AI governance. "
              "Manage stakeholder engagement with government affairs. "
              "Familiarity with AI policy is required.")
        assert has_non_ai_jd_signals(jd) is True

    def test_real_ai_role_with_one_cluster_term_not_flagged(self):
        """An AI Engineer JD that mentions 'design system' once shouldn't flag."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Build large language model inference pipelines with PyTorch. "
              "Fine-tune transformer models for production deployment. "
              "Use mlflow for the model registry and the design system.")
        assert has_non_ai_jd_signals(jd) is False


# ===================================================================
# Wave 3 #12 — "experience with AI/ML" requirement-phrase neutralizer
# ===================================================================

class TestRequirementPhraseNeutralizer:
    """Strips 'experience with X' / 'familiarity with X' / 'knowledge of X'
    spans before AI-intensity scoring. These describe what the candidate
    must KNOW (job requirement) rather than what they DO."""

    def test_experience_with_ml_stripped(self):
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Source candidates. Experience with machine learning required."
        out = _neutralize_requirement_phrases(text)
        assert "machine learning" not in out.lower()

    def test_familiarity_with_llms_stripped(self):
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Sales role. Familiarity with LLMs and PyTorch a plus."
        out = _neutralize_requirement_phrases(text)
        assert "llm" not in out.lower()
        assert "pytorch" not in out.lower()

    def test_knowledge_of_pytorch_stripped(self):
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Marketing manager. Knowledge of PyTorch helpful."
        out = _neutralize_requirement_phrases(text)
        assert "pytorch" not in out.lower()

    def test_responsibilities_phrasing_not_stripped(self):
        """Verbs like 'build', 'lead', 'train' (not requirement triggers) preserved."""
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Build deep learning models. Lead RLHF training. Train transformers."
        out = _neutralize_requirement_phrases(text)
        assert "deep learning" in out.lower()
        assert "rlhf" in out.lower()
        assert "transformers" in out.lower()

    def test_recruiter_jd_score_drops_to_zero(self):
        """Recruiter JD whose only AI signals are requirement phrases scores 0."""
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        jd = ("Source ML engineering candidates. Manage the hiring pipeline. "
              "Experience with machine learning concepts. "
              "Familiarity with LLMs and PyTorch.")
        assert compute_ai_intensity(jd) < AI_INTENSITY_THRESHOLD

    def test_real_ml_engineer_still_passes(self):
        """ML Engineer JD with both responsibilities AND requirements stays above threshold."""
        from app.services.jobs_ingest import compute_ai_intensity, AI_INTENSITY_THRESHOLD
        jd = ("Train deep learning models in production. "
              "Build PyTorch pipelines for fine-tuning large language models. "
              "Run RLHF training loops and reward model evaluation. "
              "Requirements: Experience with PyTorch, TensorFlow, JAX. "
              "Familiarity with distributed training and MLOps.")
        score = compute_ai_intensity(jd)
        assert score >= AI_INTENSITY_THRESHOLD, f"score={score}"

    def test_proficiency_in_stripped(self):
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Sales engineer. Proficiency in machine learning a plus."
        out = _neutralize_requirement_phrases(text)
        assert "machine learning" not in out.lower()

    def test_background_in_stripped(self):
        from app.services.jobs_ingest import _neutralize_requirement_phrases
        text = "Policy analyst. Background in deep learning research helpful."
        out = _neutralize_requirement_phrases(text)
        assert "deep learning" not in out.lower()


# ===================================================================
# Wave 3 #13 — bare-verb title gate (Manager/Director/Lead/Head/VP/Chief
# without AI anchor word)
# ===================================================================

class TestBareVerbTitleGate:
    """Catches 'Manager, Sales Development', 'Director, Strategic Sourcing'
    etc. — titles that start with a leadership verb but contain no AI/ML/
    research/data anchor word."""

    def test_manager_with_comma(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Manager, Sales Development") is True

    def test_director_strategic_sourcing(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Director, Strategic Sourcing") is True

    def test_senior_manager_operations(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Senior Manager, Operations") is True

    def test_head_of_customer_success(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Head of Customer Success") is True

    def test_vp_finance(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("VP, Finance") is True

    def test_chief_of_staff(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Chief of Staff") is True

    def test_principal_director(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Principal Director, Partnerships") is True

    # ---- bare-verb titles WITH AI anchor → False (gate doesn't trigger) ----

    def test_manager_ai_safety_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Manager, AI Safety") is False

    def test_manager_ml_research_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Manager, ML Research") is False

    def test_director_ai_engineering_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Director of AI Engineering") is False

    def test_senior_manager_machine_learning_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Senior Manager, Machine Learning") is False

    def test_head_of_research_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Head of Research") is False

    def test_vp_engineering_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("VP, Engineering") is False

    def test_director_alignment_passes(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Director, Alignment") is False

    # ---- non-leadership titles → False (gate doesn't apply) ----

    def test_ml_engineer_not_bare_verb(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Senior ML Engineer") is False

    def test_engineer_manager_not_bare_verb(self):
        """Title that doesn't START with Manager — e.g., 'Engineering Manager'."""
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Engineering Manager") is False

    def test_software_engineer_not_bare_verb(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Software Engineer") is False

    def test_research_scientist_not_bare_verb(self):
        from app.services.jobs_ingest import is_bare_verb_title
        assert is_bare_verb_title("Research Scientist") is False


@pytest.mark.asyncio
async def test_bare_verb_title_with_low_intensity_skipped():
    """Wave 3 #13 integration: bare-verb title + low JD intensity ⇒ auto-skip."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m, \
         patch("app.services.jobs_enrich.enrich_job_lite", new_callable=AsyncMock) as ml:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        ml.side_effect = lambda raw, **kw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            r = _raw(
                title_raw="Manager, Sales Development",
                jd_html=(
                    "<p>Drive pipeline. Close deals. Manage team of BDRs. "
                    "Familiarity with AI products is a plus.</p>"
                ),
            )
            result = await jobs_ingest._stage_one(r, "greenhouse:anthropic", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "auto-skipped" in (job.admin_notes or "")
            assert "bare-verb" in (job.admin_notes or "")
            m.assert_not_called()
            ml.assert_not_called()
    await close_db()


@pytest.mark.asyncio
async def test_bare_verb_title_with_high_intensity_proceeds():
    """Bare-verb title BUT the JD shows real AI work → enrichment proceeds."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            r = _raw(
                title_raw="Director, Engineering",
                jd_html=(
                    "<p>Lead the ML platform team. Build distributed training "
                    "infrastructure for large language model fine-tuning. "
                    "Own the model serving and inference engine.</p>"
                ),
            )
            result = await jobs_ingest._stage_one(r, "greenhouse:anthropic", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "bare-verb" not in (job.admin_notes or ""), \
                f"should NOT be auto-skipped, notes={job.admin_notes!r}"
    await close_db()


class TestHasNonAIJDSignalsWithIntensity:
    """has_non_ai_jd_signals (Wave 2) uses intensity scoring instead of
    binary substring-AI-signal check. Must preserve all RCA-026 behaviors."""

    def test_phonepe_legal_still_flagged(self):
        """The motivating PhonePe case — must remain flagged after Wave 2."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("LLB / LLM from a recognized university. Minimum 7 years of "
              "post-qualification experience in corporate legal practice. "
              "Draft and negotiate procurement contracts, MSAs, NDAs. "
              "Ensure contracts comply with Indian Contract Act.")
        assert has_non_ai_jd_signals(jd) is True

    def test_real_ml_jd_with_nda_mention_not_flagged(self):
        """Legit AI engineer JD that mentions NDA in passing — must NOT flag.
        Passes because intensity score (RLHF + fine-tuning + PyTorch + LLM) >= 5."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Train large language models with RLHF. Fine-tuning PyTorch "
              "pipelines for production. You will sign a standard NDA before starting.")
        assert has_non_ai_jd_signals(jd) is False

    def test_legal_jd_with_minimal_ai_mention_still_flagged(self):
        """Legal JD with one stray 'AI products' weak mention must still flag —
        Wave 2 closes the loophole where old binary substring check would pass."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("Manage MSAs, NDAs, and procurement contracts. LLB required. "
              "PQE 7+ years. Familiarity with AI products is a plus.")
        # >=2 non-AI cluster hits (MSA, NDA, procurement, LLB, PQE), and
        # AI intensity = 1 (weak "AI products") < 5
        assert has_non_ai_jd_signals(jd) is True

    def test_software_engineer_with_single_nda_not_flagged(self):
        """Generic SWE jd with one NDA mention — below cluster threshold."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = "Software engineer role. Backend systems. You will sign an NDA before starting."
        assert has_non_ai_jd_signals(jd) is False

    def test_llm_degree_with_law_firm_flagged(self):
        """RCA-026 carry-forward: LLM-degree + law firm = law role."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        jd = ("We are hiring an associate with LL.M. from a top law school. "
              "Law firm experience preferred. Contract drafting required.")
        assert has_non_ai_jd_signals(jd) is True

    def test_anthropic_office_manager_pattern(self):
        """About Anthropic boilerplate doesn't rescue an office-mgr role."""
        from app.services.jobs_ingest import has_non_ai_jd_signals
        # JD has no non-AI cluster signals (it's not legal/HR-coded JD body)
        # so this returns False — title pre-filter would catch "office manager" instead.
        # This test confirms the JD scanner doesn't false-positive on AI-lab boilerplate.
        jd = ("About Anthropic. Anthropic builds AI systems with machine learning. "
              "About the role. Manage office facilities and visitor logistics.")
        # No legal/HR/finance cluster hits, so returns False (correct — title would catch this)
        assert has_non_ai_jd_signals(jd) is False


# ===================================================================
# Wave 1 #4 — topic↔anchor requirement
# ===================================================================

class TestTopicAnchors:
    """Each topic must have a corresponding JD anchor; topics with no
    anchor are stripped to prevent Gemini-over-reach."""

    def test_llm_topic_with_no_anchor_stripped(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        # JD has no LLM anchor terms (no "large language model", no API names, no fine-tuning)
        jd = "Backend engineer role. Python, FastAPI, PostgreSQL, Docker."
        assert _enforce_topic_anchors(["LLM"], jd) == []

    def test_llm_topic_with_anchor_kept(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Build production systems using the OpenAI API and fine-tuning workflows."
        assert _enforce_topic_anchors(["LLM"], jd) == ["LLM"]

    def test_cv_topic_with_object_detection_kept(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Computer vision engineer working on object detection and image classification."
        assert _enforce_topic_anchors(["CV"], jd) == ["CV"]

    def test_cv_topic_without_anchors_stripped(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Backend engineer for the platform team. Python, Postgres."
        assert _enforce_topic_anchors(["CV"], jd) == []

    def test_rl_topic_with_rlhf_kept(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Train reward models for RLHF and explore policy gradient methods."
        assert _enforce_topic_anchors(["RL"], jd) == ["RL"]

    def test_nlp_topic_with_sentiment_kept(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "NLP team — work on sentiment analysis and text classification pipelines."
        assert _enforce_topic_anchors(["NLP"], jd) == ["NLP"]

    def test_applied_ml_with_pytorch_kept(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Train deep learning models in PyTorch for production deployment."
        assert _enforce_topic_anchors(["Applied ML"], jd) == ["Applied ML"]

    def test_multiple_topics_partial_strip(self):
        """Only topics without anchors are stripped; others kept."""
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = "Train large language models with RLHF. Build fine-tuning pipelines."
        # LLM, RL, Fine-tuning all have anchors. CV does not.
        assert sorted(_enforce_topic_anchors(["LLM", "CV", "RL", "Fine-tuning"], jd)) == sorted(["LLM", "RL", "Fine-tuning"])

    def test_phonepe_legal_jd_strips_applied_ml(self):
        """The motivating example: legal JD with no AI anchors → 'Applied ML' stripped."""
        from app.services.jobs_enrich import _enforce_topic_anchors
        jd = ("LLB / LLM from a recognized university. 7 years PQE in corporate "
              "legal practice. Draft procurement contracts, MSAs, NDAs.")
        assert _enforce_topic_anchors(["Applied ML"], jd) == []

    def test_empty_topic_list_passthrough(self):
        from app.services.jobs_enrich import _enforce_topic_anchors
        assert _enforce_topic_anchors([], "any jd text") == []


@pytest.mark.asyncio
async def test_prefilter_skips_enrichment_and_sets_admin_note():
    """Non-AI title should be staged with admin_notes='auto-skipped' and no AI call."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as m:
        m.side_effect = lambda raw, **kw: _fake_enrich(raw)
        async with db_module.async_session_factory() as db:
            r = _raw(title_raw="Sales Manager, Enterprise")
            result = await jobs_ingest._stage_one(r, "greenhouse:phonepe", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "auto-skipped" in (job.admin_notes or "")
            assert job.designation == "Other"  # minimal enrichment
            # Enrichment should NOT have been called.
            m.assert_not_called()
    await close_db()


# ===================================================================
# Opt #7: JD_MAX_CHARS = 4000
# ===================================================================

def test_jd_max_chars_is_4000():
    from app.services.jobs_enrich import JD_MAX_CHARS
    assert JD_MAX_CHARS == 4000


# ===================================================================
# Opt #1: Prompt caching — system_instruction split
# ===================================================================

class TestPromptSplit:
    """Verify the prompt files exist and the system prompt has no job-specific placeholders."""

    def test_system_prompt_exists(self):
        from app.services.jobs_enrich import SYSTEM_PROMPT_PATH
        assert SYSTEM_PROMPT_PATH.exists()

    def test_user_prompt_exists(self):
        from app.services.jobs_enrich import PROMPT_PATH
        assert PROMPT_PATH.exists()

    def test_system_prompt_has_no_placeholders(self):
        """System prompt must be static — no {{...}} template vars."""
        from app.services.jobs_enrich import SYSTEM_PROMPT_PATH
        text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert "{{" not in text, "System prompt must not contain template placeholders"

    def test_user_prompt_has_placeholders(self):
        """User prompt must have the dynamic template vars."""
        from app.services.jobs_enrich import PROMPT_PATH
        text = PROMPT_PATH.read_text(encoding="utf-8")
        assert "{{company}}" in text
        assert "{{jd_text}}" in text

    def test_system_prompt_has_schema(self):
        """Schema (designation enum, etc.) must be in the system prompt."""
        from app.services.jobs_enrich import SYSTEM_PROMPT_PATH
        text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert '"designation"' in text
        assert "ML Engineer" in text

    def test_system_prompt_no_summary(self):
        """Summary schema must NOT be in the system prompt (Opt #5)."""
        from app.services.jobs_enrich import SYSTEM_PROMPT_PATH
        text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert '"summary"' not in text
        assert "headline_chips" not in text
        assert "comp_snapshot" not in text


@pytest.mark.asyncio
async def test_system_instruction_passed_to_provider():
    """enrich_job must pass system_instruction kwarg to the provider."""
    await _setup()

    fake_resp = {
        "designation": "ML Engineer", "seniority": "Senior",
        "topic": ["LLM"],
        "location": {"country": "US", "country_name": "United States",
                     "city": "SF", "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 3, "max": None},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "tldr": "Build stuff.", "must_have_skills": ["Python"],
        "nice_to_have_skills": [], "roadmap_modules_matched": [],
        "description_html": "<p>JD</p>",
    }

    with patch("app.services.jobs_enrich.complete", new_callable=AsyncMock) as mock_complete, \
         patch("app.services.jobs_enrich._get_module_slugs", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.jobs_enrich._get_source_feedback", new_callable=AsyncMock, return_value=""):
        mock_complete.return_value = (fake_resp, "gemini-2.5-flash")
        from app.services.jobs_enrich import enrich_job
        await enrich_job(_raw(), source_key="greenhouse:anthropic")

        # Verify system_instruction was passed
        call_kwargs = mock_complete.call_args
        assert "system_instruction" in call_kwargs.kwargs
        assert len(call_kwargs.kwargs["system_instruction"]) > 100
        assert "designation" in call_kwargs.kwargs["system_instruction"]
    await close_db()


# ===================================================================
# Opt #5: No summary in Flash output
# ===================================================================

@pytest.mark.asyncio
async def test_enrichment_without_summary_produces_none():
    """When Flash returns no summary field, the validated output has summary=None."""
    await _setup()

    fake_resp = {
        "designation": "ML Engineer", "seniority": "Senior",
        "topic": ["LLM"],
        "location": {"country": "US", "country_name": "United States",
                     "city": "SF", "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 3, "max": None},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "tldr": "Build stuff.", "must_have_skills": ["Python"],
        "nice_to_have_skills": [], "roadmap_modules_matched": [],
        "description_html": "<p>JD</p>",
        # No "summary" key at all — simulates Flash without summary schema
    }

    with patch("app.services.jobs_enrich.complete", new_callable=AsyncMock) as mock_complete, \
         patch("app.services.jobs_enrich._get_module_slugs", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.jobs_enrich._get_source_feedback", new_callable=AsyncMock, return_value=""):
        mock_complete.return_value = (fake_resp, "gemini-2.5-flash")
        from app.services.jobs_enrich import enrich_job
        result = await enrich_job(_raw(), source_key="greenhouse:anthropic")
        assert result["summary"] is None
    await close_db()


# ===================================================================
# Opt #3: Tier-2 lightweight enrichment
# ===================================================================

class TestTier2Sources:
    """TIER2_SOURCES set and lightweight enrichment path."""

    def test_tier2_sources_defined(self):
        assert len(jobs_ingest.TIER2_SOURCES) >= 4
        assert "greenhouse:phonepe" in jobs_ingest.TIER2_SOURCES
        assert "ashby:notion" in jobs_ingest.TIER2_SOURCES

    def test_tier1_not_in_tier2(self):
        """AI-native companies must NOT be in TIER2_SOURCES."""
        assert "greenhouse:anthropic" not in jobs_ingest.TIER2_SOURCES
        assert "ashby:cohere" not in jobs_ingest.TIER2_SOURCES
        assert "greenhouse:scaleai" not in jobs_ingest.TIER2_SOURCES

    @pytest.mark.asyncio
    async def test_ensure_source_rows_tiers_tier2_sources_correctly(self):
        """TIER2_SOURCES must land as tier=2, bulk_approve=0, verified=0.

        Regression guard for RCA-025: non-AI-native companies (PhonePe, Groww,
        …) were getting T1 badges and bulk-publish eligibility, defeating the
        point of TIER2_SOURCES.
        """
        from app.models import JobSource
        await _setup()
        try:
            await jobs_ingest.ensure_source_rows()
            async with db_module.async_session_factory() as db:
                for key in jobs_ingest.TIER2_SOURCES:
                    src = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one()
                    assert src.tier == 2, f"{key}: tier={src.tier}, expected 2"
                    assert src.bulk_approve == 0, f"{key}: bulk_approve={src.bulk_approve}, expected 0"
                    slug = key.split(":", 1)[1]
                    co = (await db.execute(select(JobCompany).where(JobCompany.slug == slug))).scalar_one()
                    assert co.verified == 0, f"{slug}: verified={co.verified}, expected 0"
                # Spot-check a Tier-1 AI-native stays Tier-1.
                src = (await db.execute(select(JobSource).where(JobSource.key == "greenhouse:anthropic"))).scalar_one()
                assert src.tier == 1 and src.bulk_approve == 1
                co = (await db.execute(select(JobCompany).where(JobCompany.slug == "anthropic"))).scalar_one()
                assert co.verified == 1
        finally:
            await close_db()

    def test_lite_prompt_files_exist(self):
        from app.services.jobs_enrich import LITE_PROMPT_PATH, LITE_SYSTEM_PROMPT_PATH
        assert LITE_PROMPT_PATH.exists()
        assert LITE_SYSTEM_PROMPT_PATH.exists()

    def test_lite_system_prompt_has_no_summary(self):
        from app.services.jobs_enrich import LITE_SYSTEM_PROMPT_PATH
        text = LITE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert "summary" not in text.lower()
        assert "headline_chips" not in text

    def test_lite_system_prompt_has_no_nice_to_have(self):
        from app.services.jobs_enrich import LITE_SYSTEM_PROMPT_PATH
        text = LITE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert "nice_to_have" not in text

    def test_lite_system_prompt_has_no_modules(self):
        from app.services.jobs_enrich import LITE_SYSTEM_PROMPT_PATH
        text = LITE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert "roadmap_modules" not in text

    def test_lite_prompt_shorter_jd(self):
        """Lite user prompt should reference shorter JD (2000 chars)."""
        from app.services.jobs_enrich import LITE_PROMPT_PATH
        text = LITE_PROMPT_PATH.read_text(encoding="utf-8")
        assert "2000" in text

    def test_jd_max_chars_lite(self):
        from app.services.jobs_enrich import JD_MAX_CHARS_LITE
        assert JD_MAX_CHARS_LITE == 2000


@pytest.mark.asyncio
async def test_enrich_job_lite_returns_correct_shape():
    """enrich_job_lite must return all required keys with correct defaults."""
    fake_resp = {
        "designation": "Data Scientist", "seniority": "Mid",
        "topic": ["Applied ML"],
        "location": {"country": "IN", "country_name": "India",
                     "city": "Bangalore", "remote_policy": "Hybrid"},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 2, "max": 5},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "tldr": "Data role at PhonePe.",
        "must_have_skills": ["Python", "SQL"],
    }

    with patch("app.services.jobs_enrich.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = (fake_resp, "gemini-2.5-flash")
        from app.services.jobs_enrich import enrich_job_lite
        result = await enrich_job_lite(_raw(company="PhonePe", company_slug="phonepe"))

    # All required keys present
    assert result["designation"] == "Data Scientist"
    assert result["tldr"] == "Data role at PhonePe."
    assert result["must_have_skills"] == ["Python", "SQL"]
    # Deferred fields have safe defaults
    assert result["nice_to_have_skills"] == []
    assert result["roadmap_modules_matched"] == []
    assert result["summary"] is None
    # description_html is the raw HTML (not rewritten by LLM)
    assert "<p>" in result["description_html"]


@pytest.mark.asyncio
async def test_tier2_source_uses_lite_enrichment():
    """_stage_one for a TIER2 source should call enrich_job_lite, not enrich_job."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job_lite", new_callable=AsyncMock) as lite_mock, \
         patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as full_mock:
        lite_mock.return_value = _fake_enrich(_raw())
        async with db_module.async_session_factory() as db:
            r = _raw(company="PhonePe", company_slug="phonepe")
            result = await jobs_ingest._stage_one(r, "greenhouse:phonepe", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "tier2-lite" in (job.admin_notes or "")
            lite_mock.assert_called_once()
            full_mock.assert_not_called()
    await close_db()


@pytest.mark.asyncio
async def test_tier1_source_uses_full_enrichment():
    """_stage_one for a Tier-1 source should call enrich_job (full), not lite."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as full_mock, \
         patch("app.services.jobs_enrich.enrich_job_lite", new_callable=AsyncMock) as lite_mock:
        full_mock.return_value = _fake_enrich(_raw())
        async with db_module.async_session_factory() as db:
            r = _raw()
            result = await jobs_ingest._stage_one(r, "greenhouse:anthropic", db)
            assert result == "new"
            await db.commit()
            full_mock.assert_called_once()
            lite_mock.assert_not_called()
    await close_db()


# ===================================================================
# Opt #1: provider.complete passes system_instruction
# ===================================================================

@pytest.mark.asyncio
async def test_provider_passes_system_instruction_to_gemini():
    """provider.complete should forward system_instruction to gemini.complete."""
    from app.ai import provider

    with patch("app.ai.provider.get_settings") as mock_settings, \
         patch("app.ai.provider.is_available", return_value=True):
        s = MagicMock()
        s.gemini_api_key = "test-key"
        s.gemini_model = "gemini-2.5-flash"
        mock_settings.return_value = s

        fake_gemini = AsyncMock(return_value={"result": "ok"})
        with patch.dict("sys.modules", {}):  # force re-import
            with patch.object(provider, "_PROVIDERS", [
                ("gemini", lambda: fake_gemini,
                 lambda: Exception, lambda: Exception, "gemini_model"),
            ]):
                result, model = await provider.complete(
                    "test prompt",
                    task="jobs_enrich",
                    system_instruction="You are an extractor.",
                )
                # Gemini should receive system_instruction in kwargs
                call_kwargs = fake_gemini.call_args.kwargs
                assert call_kwargs.get("system_instruction") == "You are an extractor."


@pytest.mark.asyncio
async def test_provider_prepends_system_instruction_for_non_gemini():
    """For non-Gemini providers, system_instruction should be prepended to prompt."""
    from app.ai import provider

    with patch("app.ai.provider.get_settings") as mock_settings, \
         patch("app.ai.provider.is_available", return_value=True):
        s = MagicMock()
        s.gemini_api_key = ""  # disable gemini
        s.groq_api_key = "test-key"
        s.groq_model = "llama-3.3-70b"
        mock_settings.return_value = s

        fake_groq = AsyncMock(return_value={"result": "ok"})
        with patch.object(provider, "_PROVIDERS", [
            ("groq", lambda: fake_groq,
             lambda: Exception, lambda: Exception, "groq_model"),
        ]):
            result, model = await provider.complete(
                "test prompt",
                task="jobs_enrich",
                system_instruction="You are an extractor.",
            )
            # Groq should receive the system instruction prepended to prompt
            call_prompt = fake_groq.call_args.args[0]
            assert call_prompt.startswith("You are an extractor.")
            assert "test prompt" in call_prompt


# ===================================================================
# Integration: pre-filter + tier-2 priority
# ===================================================================

@pytest.mark.asyncio
async def test_prefilter_takes_priority_over_tier2():
    """A non-AI title on a Tier-2 board should be pre-filtered, not lite-enriched."""
    await _setup()
    with patch("app.services.jobs_enrich.enrich_job_lite", new_callable=AsyncMock) as lite_mock, \
         patch("app.services.jobs_enrich.enrich_job", new_callable=AsyncMock) as full_mock:
        async with db_module.async_session_factory() as db:
            r = _raw(title_raw="Sales Manager", company="PhonePe", company_slug="phonepe")
            result = await jobs_ingest._stage_one(r, "greenhouse:phonepe", db)
            assert result == "new"
            await db.commit()
            job = (await db.execute(select(Job))).scalar_one()
            assert "auto-skipped" in (job.admin_notes or "")
            # Neither enrichment function should be called
            lite_mock.assert_not_called()
            full_mock.assert_not_called()
    await close_db()


# ===================================================================
# Pricing table
# ===================================================================

def test_flash_lite_pricing_is_cheaper():
    """Flash-Lite must be cheaper than Flash."""
    from app.ai.pricing import get_price
    flash_in, flash_out = get_price("gemini", "gemini-2.5-flash")
    lite_in, lite_out = get_price("gemini", "gemini-2.0-flash-lite")
    assert lite_in < flash_in
    assert lite_out < flash_out


# ===================================================================
# Phase 14.7: JD-hash dedup cache
# ===================================================================

class TestJDDedupCache:
    """LRU cache for identical JD texts — skips AI call on cache hit."""

    def setup_method(self):
        """Clear the cache between tests."""
        from app.services.jobs_enrich import _enrich_cache
        _enrich_cache.clear()

    def test_cache_put_and_get(self):
        from app.services.jobs_enrich import _cache_get, _cache_put
        _cache_put("abc", {"designation": "ML Engineer"})
        assert _cache_get("abc") == {"designation": "ML Engineer"}

    def test_cache_miss_returns_none(self):
        from app.services.jobs_enrich import _cache_get
        assert _cache_get("nonexistent") is None

    def test_cache_evicts_oldest(self):
        from app.services.jobs_enrich import _cache_get, _cache_put, _ENRICH_CACHE_MAX
        # Fill cache to max
        for i in range(_ENRICH_CACHE_MAX):
            _cache_put(f"key-{i}", {"i": i})
        # All should be present
        assert _cache_get("key-0") is not None
        assert _cache_get(f"key-{_ENRICH_CACHE_MAX - 1}") is not None
        # Add one more — oldest (key-0) was just accessed so key-1 is oldest
        _cache_put("overflow", {"overflow": True})
        assert _cache_get("overflow") is not None
        assert _cache_get("key-1") is None  # evicted

    def test_jd_hash_stable(self):
        from app.services.jobs_enrich import _jd_hash
        h1 = _jd_hash("Build LLMs at scale. Must have PyTorch.")
        h2 = _jd_hash("Build LLMs at scale. Must have PyTorch.")
        assert h1 == h2

    def test_jd_hash_case_insensitive(self):
        from app.services.jobs_enrich import _jd_hash
        h1 = _jd_hash("Build LLMs at Scale")
        h2 = _jd_hash("build llms at scale")
        assert h1 == h2

    def test_jd_hash_differs_for_different_text(self):
        from app.services.jobs_enrich import _jd_hash
        h1 = _jd_hash("Build LLMs at scale.")
        h2 = _jd_hash("Build computer vision models.")
        assert h1 != h2

    def test_enrich_cache_stats(self):
        from app.services.jobs_enrich import _cache_put, enrich_cache_stats
        _cache_put("k1", {"x": 1})
        _cache_put("k2", {"x": 2})
        stats = enrich_cache_stats()
        assert stats["size"] == 2
        assert stats["max"] == 256


@pytest.mark.asyncio
async def test_enrich_job_uses_cache_on_identical_jd():
    """Second call with identical JD text should hit cache and skip AI."""
    from app.services.jobs_enrich import _enrich_cache
    _enrich_cache.clear()

    fake_resp = {
        "designation": "ML Engineer", "seniority": "Senior",
        "topic": ["LLM"],
        "location": {"country": "US", "country_name": "United States",
                     "city": "SF", "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 3, "max": None},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "tldr": "Build stuff.", "must_have_skills": ["Python"],
        "nice_to_have_skills": [], "roadmap_modules_matched": [],
        "description_html": "<p>JD</p>",
    }

    with patch("app.services.jobs_enrich.complete", new_callable=AsyncMock) as mock_complete, \
         patch("app.services.jobs_enrich._get_module_slugs", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.jobs_enrich._get_source_feedback", new_callable=AsyncMock, return_value=""):
        mock_complete.return_value = (fake_resp, "gemini-2.5-flash")
        from app.services.jobs_enrich import enrich_job

        # First call — cache miss, calls AI
        r1 = _raw()
        result1 = await enrich_job(r1, source_key="greenhouse:anthropic")
        assert mock_complete.call_count == 1
        assert result1["designation"] == "ML Engineer"

        # Second call with same JD — cache hit, no AI call
        r2 = _raw(external_id="gh-2", title_raw="Another ML Engineer")
        result2 = await enrich_job(r2, source_key="greenhouse:anthropic")
        assert mock_complete.call_count == 1  # still 1 — cache hit!
        assert result2["designation"] == "ML Engineer"
        # But title_raw should reflect the second job (validation per-job)
        assert result2["title_raw"] == "Another ML Engineer"

    _enrich_cache.clear()


@pytest.mark.asyncio
async def test_enrich_job_cache_miss_on_different_jd():
    """Different JD text should miss cache and call AI again."""
    from app.services.jobs_enrich import _enrich_cache
    _enrich_cache.clear()

    fake_resp = {
        "designation": "ML Engineer", "seniority": "Senior", "topic": ["LLM"],
        "location": {"country": "US", "country_name": "US", "city": "SF",
                     "remote_policy": "Hybrid", "regions_allowed": []},
        "employment": {"job_type": "Full-time", "shift": "Day",
                       "experience_years": {"min": 3, "max": None},
                       "salary": {"min": None, "max": None, "currency": None, "disclosed": False}},
        "tldr": "Build stuff.", "must_have_skills": ["Python"],
        "nice_to_have_skills": [], "roadmap_modules_matched": [],
        "description_html": "<p>JD</p>",
    }

    with patch("app.services.jobs_enrich.complete", new_callable=AsyncMock) as mock_complete, \
         patch("app.services.jobs_enrich._get_module_slugs", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.jobs_enrich._get_source_feedback", new_callable=AsyncMock, return_value=""):
        mock_complete.return_value = (fake_resp, "gemini-2.5-flash")
        from app.services.jobs_enrich import enrich_job

        r1 = _raw(jd_html="<p>Build LLMs at scale.</p>")
        await enrich_job(r1, source_key="greenhouse:anthropic")
        assert mock_complete.call_count == 1

        r2 = _raw(jd_html="<p>Build computer vision models.</p>", external_id="gh-2")
        await enrich_job(r2, source_key="greenhouse:anthropic")
        assert mock_complete.call_count == 2  # different JD, cache miss

    _enrich_cache.clear()


# ===================================================================
# Phase 14.6: Module-match backfill (derive_modules)
# ===================================================================

def test_derive_modules_from_skills():
    """derive_modules should return template keys matching job skills."""
    # This test exercises the function in isolation; it relies on
    # published templates existing. If none published, returns [].
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from backfill_modules_matched import derive_modules

    data = {
        "must_have_skills": ["PyTorch", "Distributed training", "RLHF"],
        "topic": ["LLM", "Safety"],
    }
    modules = derive_modules(data)
    # Should return a list (possibly empty if no templates loaded)
    assert isinstance(modules, list)
    assert len(modules) <= 6  # capped at 6


def test_derive_modules_empty_skills():
    """Empty skills should return empty modules."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from backfill_modules_matched import derive_modules

    assert derive_modules({"must_have_skills": [], "topic": []}) == []
    assert derive_modules({}) == []
