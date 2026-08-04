"""
Unit tests for LangSmith tracing isolation across multiple applications.

This ensures that when multiple apps use agent-harness, their traces
don't get mixed in the same LangSmith project.
"""
import os
import pytest
from unittest.mock import patch
from agent_harness.agent_factory import AgentFactory


class TestLangSmithIsolation:
    """Test LangSmith project isolation for multi-app deployments."""

    def setup_method(self):
        """Clean environment before each test."""
        # Remove any LangSmith env vars
        for key in ["LANGSMITH_TRACING", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"]:
            if key in os.environ:
                del os.environ[key]

    def teardown_method(self):
        """Clean environment after each test."""
        # Remove any LangSmith env vars
        for key in ["LANGSMITH_TRACING", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"]:
            if key in os.environ:
                del os.environ[key]

    def test_tracing_disabled_when_env_var_not_set(self):
        """Test that nothing happens if LANGSMITH_TRACING is not set."""
        factory = AgentFactory()

        # LangSmith env vars should not be set
        assert os.environ.get("LANGSMITH_TRACING") != "true"
        assert "LANGSMITH_PROJECT" not in os.environ

    def test_warning_logged_when_project_not_specified(self, caplog):
        """Test that warning is logged when LANGSMITH_TRACING=true but no project."""
        os.environ["LANGSMITH_TRACING"] = "true"

        with caplog.at_level("WARNING"):
            factory = AgentFactory()

        # Should log warning about missing project
        assert "LANGSMITH_PROJECT is not set" in caplog.text
        assert "cross-app trace contamination" in caplog.text

        # Tracing should be disabled (LANGSMITH_PROJECT not set)
        assert "LANGSMITH_PROJECT" not in os.environ or os.environ.get("LANGSMITH_PROJECT") == ""

    def test_project_configured_via_configure_method(self, caplog):
        """Test that project is configured via configure_observability() method."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        with caplog.at_level("INFO"):
            factory.configure_observability(langsmith_project="crm-app")

        # Should log success message
        assert "LangSmith tracing enabled" in caplog.text
        assert "project=crm-app" in caplog.text

        # Project should be set in environment
        assert os.environ.get("LANGSMITH_PROJECT") == "crm-app"
        assert os.environ.get("LANGSMITH_TRACING") == "true"

    def test_project_configured_via_env_var(self, caplog):
        """Test that project is configured when set via env var."""
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = "support-app"

        with caplog.at_level("INFO"):
            factory = AgentFactory()

        # Should log success message
        assert "LangSmith tracing enabled" in caplog.text
        assert "project=support-app" in caplog.text

        # Project should remain in environment
        assert os.environ.get("LANGSMITH_PROJECT") == "support-app"
        assert os.environ.get("LANGSMITH_TRACING") == "true"

    def test_configure_method_overrides_env_var(self, caplog):
        """Test that configure_observability() overrides env var."""
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = "env-project"

        factory = AgentFactory()  # Will use env-project initially

        with caplog.at_level("INFO"):
            # Reconfigure with different project
            factory.configure_observability(langsmith_project="method-project")

        # Should use method value, not env var
        assert "project=method-project" in caplog.text
        assert os.environ.get("LANGSMITH_PROJECT") == "method-project"

    def test_default_endpoint_set_if_not_specified(self):
        """Test that default LangSmith endpoint is set."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()
        factory.configure_observability(langsmith_project="test-app")

        # Default endpoint should be set
        assert os.environ.get("LANGSMITH_ENDPOINT") == "https://api.smith.langchain.com"

    def test_custom_endpoint_preserved(self):
        """Test that custom endpoint is not overwritten."""
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_ENDPOINT"] = "https://custom.langsmith.io"

        factory = AgentFactory()
        factory.configure_observability(langsmith_project="test-app")

        # Custom endpoint should be preserved
        assert os.environ.get("LANGSMITH_ENDPOINT") == "https://custom.langsmith.io"

    def test_multiple_configure_calls_with_different_projects(self, caplog):
        """Test that multiple configure calls can set different projects (isolation)."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        with caplog.at_level("INFO"):
            # Configure for CRM app
            factory.configure_observability(langsmith_project="crm-app")
            project1 = os.environ.get("LANGSMITH_PROJECT")

            # Reconfigure for Support app
            factory.configure_observability(langsmith_project="support-app")
            project2 = os.environ.get("LANGSMITH_PROJECT")

        # Each configure call should set its own project
        # (Note: In real usage, each app would run in separate process/container)
        assert "crm-app" in caplog.text
        assert "support-app" in caplog.text

        # Last configure wins in the same process (expected behavior)
        assert project2 == "support-app"

    def test_no_default_project_prevents_contamination(self, caplog):
        """Test that missing project prevents accidental trace mixing."""
        os.environ["LANGSMITH_TRACING"] = "true"

        # Create factory without specifying project
        factory = AgentFactory()

        # Should warn and NOT enable tracing
        assert "cross-app trace contamination" in caplog.text

        # Configure with explicit project
        factory.configure_observability(langsmith_project="explicit-app")

        # Should work fine after configuration
        assert os.environ.get("LANGSMITH_PROJECT") == "explicit-app"

        # This ensures App without explicit config doesn't contaminate others


class TestLangSmithBackwardCompatibility:
    """Test backward compatibility with existing deployments."""

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

    def test_existing_deployment_with_env_var_still_works(self, caplog):
        """Test that existing deployments using env var continue to work."""
        # Existing deployment pattern
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = "my-existing-app"

        with caplog.at_level("INFO"):
            factory = AgentFactory()  # No parameter needed

        # Should work as before
        assert "LangSmith tracing enabled" in caplog.text
        assert os.environ.get("LANGSMITH_PROJECT") == "my-existing-app"

    def test_new_deployment_with_configure_method(self, caplog):
        """Test new recommended pattern using configure_observability()."""
        os.environ["LANGSMITH_TRACING"] = "true"

        factory = AgentFactory()

        with caplog.at_level("INFO"):
            factory.configure_observability(langsmith_project="new-app")

        # Should work with new pattern
        assert "LangSmith tracing enabled" in caplog.text
        assert os.environ.get("LANGSMITH_PROJECT") == "new-app"
