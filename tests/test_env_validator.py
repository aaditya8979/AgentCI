"""
Tests for environment validation.
"""
import os
import pytest
from unittest.mock import patch

from agentci.env_validator import validate_environment


class TestEnvironmentValidation:

    def test_missing_all_raises_with_all_names(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError) as exc_info:
                validate_environment(include_webhook=True)

            msg = str(exc_info.value)
            assert "DATABASE_URL" in msg
            assert "REDIS_URL" in msg
            assert "TEMPORAL_HOST" in msg
            assert "GITHUB_WEBHOOK_SECRET" in msg
            assert "AGENTCI_API_KEYS" in msg
            assert "[Database]" in msg
            assert ".env.example" in msg

    def test_missing_one_raises_with_that_name(self):
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "REDIS_URL": "redis://localhost",
            "TEMPORAL_HOST": "localhost:7233",
            "GITHUB_WEBHOOK_SECRET": "secret",
            # Missing AGENTCI_API_KEYS
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(EnvironmentError) as exc_info:
                validate_environment(include_webhook=True)

            msg = str(exc_info.value)
            assert "AGENTCI_API_KEYS" in msg
            # Should NOT mention vars that are set
            assert "DATABASE_URL" not in msg

    def test_all_set_passes(self):
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "REDIS_URL": "redis://localhost",
            "TEMPORAL_HOST": "localhost:7233",
            "GITHUB_WEBHOOK_SECRET": "secret",
            "AGENTCI_API_KEYS": "key1,key2",
        }
        with patch.dict(os.environ, env, clear=True):
            # Should not raise
            validate_environment(include_webhook=True)

    def test_without_webhook_skips_github_vars(self):
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "REDIS_URL": "redis://localhost",
            "TEMPORAL_HOST": "localhost:7233",
        }
        with patch.dict(os.environ, env, clear=True):
            # Should not raise — webhook vars not required
            validate_environment(include_webhook=False)
