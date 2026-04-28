import pytest
from pydantic import ValidationError

from app.ai.schemas import (
    ReasoningTrail,
    SocialDraftSchema,
    SocialCurateOutput,
)


def _trail():
    return ReasoningTrail(
        score_justification="A solid 30-character explanation here.",
        evidence_sources=["source title: \"Test\"", "tag slug: rag"],
        uncertainty_factors=[],
    )


def _twitter(body="Short tweet body. https://example.com/x", hashtags=("#RAG",)):
    return SocialDraftSchema(
        platform="twitter", body=body, hashtags=list(hashtags), reasoning=_trail()
    )


def _linkedin(
    body="LinkedIn body line one.\n\nRead more: https://example.com/x",
    hashtags=("#RAG", "#AIEngineering", "#PromptEngineering", "#AutomateEdge"),
):
    return SocialDraftSchema(
        platform="linkedin", body=body, hashtags=list(hashtags), reasoning=_trail()
    )


# -- happy paths ----------------------------------------------------------

def test_twitter_happy_path():
    d = _twitter()
    assert d.platform == "twitter"


def test_linkedin_happy_path():
    d = _linkedin()
    assert d.hashtags[-1] == "#AutomateEdge"


def test_curate_output_happy_path():
    out = SocialCurateOutput(twitter=_twitter(), linkedin=_linkedin())
    assert out.twitter.platform == "twitter"


# -- reasoning trail rejects ----------------------------------------------

def test_reject_empty_evidence():
    with pytest.raises(ValidationError, match="evidence_sources"):
        ReasoningTrail(
            score_justification="A solid explanation here for why.",
            evidence_sources=[],
            uncertainty_factors=[],
        )


# -- twitter rejects ------------------------------------------------------

def test_reject_twitter_overlength():
    long_body = "x" * 281
    with pytest.raises(ValidationError, match=r"> 280"):
        _twitter(body=long_body)


def test_reject_twitter_too_many_tags():
    with pytest.raises(ValidationError, match="1-2 hashtags"):
        _twitter(hashtags=("#RAG", "#AIEngineering", "#MLEngineering"))


def test_reject_twitter_includes_brand():
    with pytest.raises(ValidationError, match="#AutomateEdge"):
        _twitter(hashtags=("#RAG", "#AutomateEdge"))


# -- linkedin rejects -----------------------------------------------------

def test_reject_linkedin_overlength():
    long_body = "x" * 3001
    with pytest.raises(ValidationError, match=r"> 3000"):
        _linkedin(body=long_body)


def test_reject_linkedin_too_few_tags():
    with pytest.raises(ValidationError, match="3-5 hashtags"):
        _linkedin(hashtags=("#RAG", "#AutomateEdge"))


def test_reject_linkedin_too_many_tags():
    with pytest.raises(ValidationError, match="3-5 hashtags"):
        _linkedin(hashtags=(
            "#RAG", "#AIEngineering", "#PromptEngineering",
            "#MLEngineering", "#NLP", "#AutomateEdge",
        ))


def test_reject_linkedin_missing_brand_last():
    with pytest.raises(ValidationError, match="end with #AutomateEdge"):
        _linkedin(hashtags=("#RAG", "#AIEngineering", "#PromptEngineering"))


# -- hashtag format rejects -----------------------------------------------

def test_reject_lowercase_hashtag():
    with pytest.raises(ValidationError, match="canonical form"):
        _twitter(hashtags=("#rag",))


def test_reject_hyphenated_hashtag():
    with pytest.raises(ValidationError, match="canonical form"):
        _twitter(hashtags=("#prompt-engineering",))


# -- inline hashtag reject ------------------------------------------------

def test_reject_inline_hashtag_in_body():
    with pytest.raises(ValidationError, match="inline"):
        _twitter(body="Use #RAG to fix this. https://example.com/x")


# -- platform mismatch ----------------------------------------------------

def test_reject_platform_mismatch_in_curate_output():
    swapped_twitter = _twitter()
    swapped_linkedin = _linkedin()
    # Try to put linkedin draft in twitter slot
    with pytest.raises(ValidationError):
        SocialCurateOutput(twitter=swapped_linkedin, linkedin=swapped_twitter)


# -- prompt builder -------------------------------------------------------

def test_prompt_builder_substitutes_both_placeholders():
    from app.ai.social_curate import build_prompt, get_template
    template = get_template()
    assert "{{TAG_MAP}}" not in template, "TAG_MAP must be substituted at module load"
    assert "{{SOURCE_JSON}}" in template, "SOURCE_JSON must remain for per-call sub"
    rendered = build_prompt({"kind": "blog", "slug": "test", "tags": ["rag"]})
    assert "{{TAG_MAP}}" not in rendered
    assert "{{SOURCE_JSON}}" not in rendered
    assert "rag" in rendered  # source content present


def test_prompt_builder_includes_canonical_tags():
    from app.ai.social_curate import get_template
    template = get_template()
    # Sample of brand-canonical tags must be present in the rendered map
    assert "#RAG" in template
    assert "#AIEngineering" in template
    assert "#PromptEngineering" in template
