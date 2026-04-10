"""Tests for AI sanitizer and provider (Tasks 7.1, 7.4).

AC 7.1: Unit tests cover common secret patterns
AC 7.4: Mocked tests cover success + fallback paths
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.ai.sanitize import (
    contains_secrets,
    is_excluded_file,
    redact_secrets,
    sanitize_file_list,
)


# ---- 7.1: Sanitizer tests ----

class TestExcludedFiles:
    def test_env_file(self):
        assert is_excluded_file(".env") is True
        assert is_excluded_file(".env.local") is True
        assert is_excluded_file("config/.env.prod") is True

    def test_secret_files(self):
        assert is_excluded_file("secrets.yaml") is True
        assert is_excluded_file("credentials.json") is True
        assert is_excluded_file("id_rsa") is True
        assert is_excluded_file("id_rsa.pub") is True

    def test_key_files(self):
        assert is_excluded_file("server.pem") is True
        assert is_excluded_file("private.key") is True
        assert is_excluded_file("cert.p12") is True

    def test_normal_files(self):
        assert is_excluded_file("main.py") is False
        assert is_excluded_file("README.md") is False
        assert is_excluded_file("requirements.txt") is False
        assert is_excluded_file("src/app.js") is False


class TestContainsSecrets:
    def test_openai_key(self):
        assert contains_secrets("sk-abcdefghijklmnopqrstuvwx") is True

    def test_github_pat(self):
        assert contains_secrets("ghp_abcdefghijklmnopqrstuvwxyz1234567890") is True

    def test_google_api_key(self):
        assert contains_secrets("AIzaSyD-abc_def-ghi_jkl_mno_pqr_stu_vwxyz") is True

    def test_aws_key(self):
        assert contains_secrets("AKIAIOSFODNN7EXAMPLE") is True

    def test_private_key_header(self):
        assert contains_secrets("-----BEGIN RSA PRIVATE KEY-----") is True

    def test_normal_code(self):
        assert contains_secrets("def hello(): return 'world'") is False
        assert contains_secrets("import os\nprint('hello')") is False


class TestRedactSecrets:
    def test_redacts_openai_key(self):
        text = "API_KEY=sk-abcdefghijklmnopqrstuvwx"
        result = redact_secrets(text)
        assert "sk-" not in result
        assert "[REDACTED]" in result

    def test_preserves_normal_text(self):
        text = "Hello world, this is normal code"
        assert redact_secrets(text) == text


class TestSanitizeFileList:
    def test_removes_env_files(self):
        files = [
            {"path": ".env", "content": "SECRET=abc"},
            {"path": "main.py", "content": "print('hello')"},
        ]
        result = sanitize_file_list(files)
        assert len(result) == 1
        assert result[0]["path"] == "main.py"

    def test_redacts_secrets_in_remaining_files(self):
        files = [
            {"path": "config.py", "content": "key = 'sk-abcdefghijklmnopqrstuvwx'"},
        ]
        result = sanitize_file_list(files)
        assert "[REDACTED]" in result[0]["content"]


# ---- 7.4: Provider tests ----

@pytest.mark.asyncio
async def test_provider_gemini_success():
    """Provider returns Gemini result on success."""
    with patch("app.ai.provider.gemini_complete", new_callable=AsyncMock) as mock_gemini:
        mock_gemini.return_value = {"score": 85}
        from app.ai.provider import complete
        result, model = await complete("test prompt")
        assert result["score"] == 85
        mock_gemini.assert_called_once()


@pytest.mark.asyncio
async def test_provider_falls_back_to_groq():
    """Provider falls back to Groq when Gemini fails."""
    from app.ai.gemini import GeminiError

    with patch("app.ai.provider.gemini_complete", new_callable=AsyncMock) as mock_gemini, \
         patch("app.ai.provider.groq_complete", new_callable=AsyncMock) as mock_groq:
        mock_gemini.side_effect = GeminiError("Gemini down")
        mock_groq.return_value = {"score": 70}
        from app.ai.provider import complete
        result, model = await complete("test prompt")
        assert result["score"] == 70
        mock_groq.assert_called_once()


@pytest.mark.asyncio
async def test_provider_all_fail():
    """Provider raises AIProviderError when all providers fail."""
    from app.ai.gemini import GeminiError
    from app.ai.groq import GroqError
    from app.ai.provider import AIProviderError

    with patch("app.ai.provider.gemini_complete", new_callable=AsyncMock) as mock_gemini, \
         patch("app.ai.provider.groq_complete", new_callable=AsyncMock) as mock_groq:
        mock_gemini.side_effect = GeminiError("down")
        mock_groq.side_effect = GroqError("also down")
        from app.ai.provider import complete
        with pytest.raises(AIProviderError):
            await complete("test prompt")
