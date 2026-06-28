"""Unit tests for src/utils.py."""
import os
from unittest.mock import patch

import pytest


class TestSetupLangfuseTracing:
    def test_missing_vars_raises(self):
        from src.utils import setup_langfuse_tracing

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="Missing LangFuse env vars"):
                setup_langfuse_tracing()

    def test_partial_vars_raises(self):
        from src.utils import setup_langfuse_tracing

        env = {"LANGFUSE_PUBLIC_KEY": "pk_test", "LANGFUSE_SECRET_KEY": "sk_test"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="LANGFUSE_HOST"):
                setup_langfuse_tracing()

    def test_all_vars_present_calls_get_client(self):
        from src.utils import setup_langfuse_tracing

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk_test",
            "LANGFUSE_SECRET_KEY": "sk_test",
            "LANGFUSE_HOST": "https://cloud.langfuse.com",
        }
        with (
            patch.dict(os.environ, env),
            patch("src.utils.get_client") as mock_gc,
        ):
            setup_langfuse_tracing()
            mock_gc.assert_called_once()


class TestConfigureModelBackend:
    def test_proxy_enabled_sets_base_url(self, monkeypatch):
        monkeypatch.setenv("USE_LITELLM_PROXY", "true")
        monkeypatch.setenv("LITELLM_PROXY_URL", "https://proxy.example.com")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        from src.utils import configure_model_backend
        configure_model_backend()

        assert os.environ["ANTHROPIC_BASE_URL"] == "https://proxy.example.com"
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-real-key"  # unchanged

    def test_proxy_enabled_empty_url_does_not_set_base_url(self, monkeypatch):
        monkeypatch.setenv("USE_LITELLM_PROXY", "true")
        monkeypatch.setenv("LITELLM_PROXY_URL", "")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        from src.utils import configure_model_backend
        configure_model_backend()

        assert "ANTHROPIC_BASE_URL" not in os.environ

    def test_proxy_disabled_removes_base_url(self, monkeypatch):
        monkeypatch.setenv("USE_LITELLM_PROXY", "false")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://should-be-removed.example.com")

        from src.utils import configure_model_backend
        configure_model_backend()

        assert "ANTHROPIC_BASE_URL" not in os.environ

    def test_proxy_disabled_default_removes_base_url(self, monkeypatch):
        monkeypatch.delenv("USE_LITELLM_PROXY", raising=False)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://should-be-removed.example.com")

        from src.utils import configure_model_backend
        configure_model_backend()

        assert "ANTHROPIC_BASE_URL" not in os.environ
