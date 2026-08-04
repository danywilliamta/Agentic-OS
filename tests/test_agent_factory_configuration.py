"""
Unit tests for AgentFactory configuration methods.

Tests for configure_token_tracker() and configure_observability() methods.
"""
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from agent_harness.agent_factory import AgentFactory


class TestConfigureTokenTracker:
    """Test AgentFactory.configure_token_tracker() method."""

    def setup_method(self):
        """Clean environment before each test."""
        if "DATABASE_URL" in os.environ:
            self._saved_database_url = os.environ["DATABASE_URL"]
            del os.environ["DATABASE_URL"]
        else:
            self._saved_database_url = None

    def teardown_method(self):
        """Restore environment after each test."""
        if self._saved_database_url:
            os.environ["DATABASE_URL"] = self._saved_database_url
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]

    def test_configure_token_tracker_enabled(self):
        """Test enabling token tracker via configure method."""
        factory = AgentFactory()

        # Initially no token tracker config
        assert factory._token_tracker_config == {}

        # Configure token tracking
        factory.configure_token_tracker({
            "enabled": True,
            "connection_string": "sqlite:///test.db"
        })

        # Config should be updated
        assert factory._token_tracker_config["enabled"] is True
        assert factory._token_tracker_config["connection_string"] == "sqlite:///test.db"

        # Tracker should be reset for reconfiguration
        assert factory._token_tracker is None

    def test_configure_token_tracker_disabled(self):
        """Test disabling token tracker via configure method."""
        factory = AgentFactory()

        # Configure as disabled
        factory.configure_token_tracker({"enabled": False})

        # Config should be updated
        assert factory._token_tracker_config["enabled"] is False
        assert factory._token_tracker is None

    def test_configure_token_tracker_resets_existing_tracker(self):
        """Test that reconfiguring resets the existing tracker."""
        factory = AgentFactory()

        # Set a mock tracker
        factory._token_tracker = MagicMock()

        # Reconfigure
        factory.configure_token_tracker({"enabled": True})

        # Tracker should be reset
        assert factory._token_tracker is None

    def test_auto_configure_from_database_url(self):
        """Test auto-configuration when DATABASE_URL is set."""
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

        factory = AgentFactory()

        # Should auto-configure from DATABASE_URL
        assert factory._token_tracker_config["enabled"] is True

    def test_no_auto_configure_without_database_url(self):
        """Test no auto-configuration when DATABASE_URL is not set."""
        factory = AgentFactory()

        # Should not auto-configure
        assert factory._token_tracker_config == {}

    def test_explicit_config_overrides_auto_config(self):
        """Test that explicit config takes precedence over DATABASE_URL."""
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

        factory = AgentFactory(token_tracker_config={"enabled": False})

        # Explicit config should override auto-config
        assert factory._token_tracker_config["enabled"] is False


class TestConfigureObservability:
    """Test AgentFactory.configure_observability() method."""

    def setup_method(self):
        """Clean environment before each test."""
        for key in ["LANGSMITH_TRACING", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"]:
            if key in os.environ:
                del os.environ[key]

    def teardown_method(self):
        """Clean environment after each test."""
        for key in ["LANGSMITH_TRACING", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"]:
            if key in os.environ:
                del os.environ[key]

    def test_configure_observability_sets_project(self, caplog):
        """Test configuring observability with project name."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        with caplog.at_level("INFO"):
            factory.configure_observability(langsmith_project="test-project")

        # Should set project
        assert os.environ.get("LANGSMITH_PROJECT") == "test-project"
        assert "LangSmith tracing enabled" in caplog.text
        assert "project=test-project" in caplog.text

    def test_configure_observability_without_tracing_enabled(self):
        """Test configuring observability when tracing is not enabled."""
        factory = AgentFactory()

        # Should not do anything if LANGSMITH_TRACING is not set
        factory.configure_observability(langsmith_project="test-project")

        # Project should not be set
        assert "LANGSMITH_PROJECT" not in os.environ

    def test_configure_observability_warns_without_project(self, caplog):
        """Test warning when tracing enabled but no project specified."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        with caplog.at_level("WARNING"):
            factory.configure_observability()

        # Should warn about missing project
        assert "LANGSMITH_PROJECT is not set" in caplog.text
        assert "cross-app trace contamination" in caplog.text

    def test_configure_observability_can_reconfigure(self, caplog):
        """Test reconfiguring observability with different project."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        # Configure first time
        factory.configure_observability(langsmith_project="project-1")
        assert os.environ.get("LANGSMITH_PROJECT") == "project-1"

        # Reconfigure with different project
        with caplog.at_level("INFO"):
            factory.configure_observability(langsmith_project="project-2")

        # Should update to new project
        assert os.environ.get("LANGSMITH_PROJECT") == "project-2"
        assert "project=project-2" in caplog.text


class TestAgentFactoryInitialization:
    """Test AgentFactory initialization with various configurations."""

    def setup_method(self):
        """Clean environment before each test."""
        for key in ["DATABASE_URL", "LANGSMITH_TRACING", "LANGSMITH_PROJECT"]:
            if key in os.environ:
                del os.environ[key]

    def teardown_method(self):
        """Clean environment after each test."""
        for key in ["DATABASE_URL", "LANGSMITH_TRACING", "LANGSMITH_PROJECT"]:
            if key in os.environ:
                del os.environ[key]

    def test_factory_init_with_no_config(self):
        """Test factory initialization with no configuration."""
        factory = AgentFactory()

        # Should have empty token tracker config
        assert factory._token_tracker_config == {}

        # Should have empty agents cache
        assert factory.agents_cache == {}

        # Should have no token tracker
        assert factory._token_tracker is None

    def test_factory_init_with_token_tracker_config(self):
        """Test factory initialization with token tracker config."""
        config = {
            "enabled": True,
            "connection_string": "sqlite:///test.db"
        }

        factory = AgentFactory(token_tracker_config=config)

        # Should store config
        assert factory._token_tracker_config == config

    def test_factory_init_auto_detects_database_url(self):
        """Test factory auto-detects DATABASE_URL."""
        os.environ["DATABASE_URL"] = "postgresql://localhost/test"

        factory = AgentFactory()

        # Should auto-configure token tracking
        assert factory._token_tracker_config["enabled"] is True

    def test_factory_init_configures_langsmith_from_env(self, caplog):
        """Test factory configures LangSmith from environment variables."""
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = "env-project"

        with caplog.at_level("INFO"):
            factory = AgentFactory()

        # Should configure LangSmith from env
        assert "LangSmith tracing enabled" in caplog.text
        assert "project=env-project" in caplog.text

    def test_factory_init_warns_if_langsmith_tracing_without_project(self, caplog):
        """Test factory warns if tracing enabled but no project."""
        os.environ["LANGSMITH_TRACING"] = "true"

        with caplog.at_level("WARNING"):
            factory = AgentFactory()

        # Should warn about missing project
        assert "LANGSMITH_PROJECT is not set" in caplog.text
        assert "cross-app trace contamination" in caplog.text
