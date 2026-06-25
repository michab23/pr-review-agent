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
