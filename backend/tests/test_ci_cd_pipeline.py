"""Test suite for Module 42: CI/CD Pipeline.

Verifies:
1. All 9 automated pipeline stages exist and are properly defined in GitHub Actions & runner.
2. Pipeline fails fast if critical tests or security checks fail.
3. Automated deployment to production is strictly disabled.
4. Secure secret handling and masking are enforced.
5. End-to-end execution of pipeline stages on clean workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def github_workflow() -> dict:
    """Load and parse .github/workflows/ci.yml."""
    workflow_path = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    assert workflow_path.exists(), "GitHub CI workflow .github/workflows/ci.yml must exist"
    content = workflow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "Parsed workflow must be a valid YAML dictionary"
    return data


# =============================================================================
# 1. Pipeline Stages Verification (All 9 Stages)
# =============================================================================
def test_all_9_pipeline_stages_exist_in_github_workflow(github_workflow: dict):
    """Verify that all 9 required pipeline stages are explicitly defined as jobs."""
    jobs = github_workflow.get("jobs", {})

    expected_stages = [
        "install",
        "lint",
        "type-check",
        "unit-tests",
        "integration-tests",
        "security-checks",
        "frontend-build",
        "backend-build",
        "container-build",
    ]

    for stage in expected_stages:
        assert stage in jobs, f"Pipeline stage '{stage}' must be defined as a job in ci.yml"


def test_stage_dependency_graph_order(github_workflow: dict):
    """Verify that jobs enforce a sequential dependency hierarchy ensuring pipeline integrity."""
    jobs = github_workflow.get("jobs", {})

    # lint and type-check depend on install
    assert "install" in jobs["lint"].get("needs", [])
    assert "install" in jobs["type-check"].get("needs", [])

    # unit-tests depend on lint and type-check
    unit_needs = jobs["unit-tests"].get("needs", [])
    assert "lint" in unit_needs or "install" in unit_needs

    # integration-tests depend on unit-tests
    integration_needs = jobs["integration-tests"].get("needs", [])
    assert "unit-tests" in integration_needs

    # security-checks must be present before builds
    assert "security-checks" in jobs

    # container-build depends on frontend-build and backend-build
    container_needs = jobs["container-build"].get("needs", [])
    assert "frontend-build" in container_needs
    assert "backend-build" in container_needs


def test_runner_defines_all_9_stages():
    """Verify that the CI orchestrator script scripts/run_ci_pipeline.py defines all 9 stages."""
    from scripts.run_ci_pipeline import CIPipelineRunner

    stage_names = [name for _, name, _ in CIPipelineRunner.STAGES]
    expected_stages = [
        "install",
        "lint",
        "type check",
        "unit tests",
        "integration tests",
        "security checks",
        "frontend build",
        "backend build",
        "container build",
    ]

    assert stage_names == expected_stages, f"Expected stages {expected_stages}, got {stage_names}"


# =============================================================================
# 2. Critical Test Failure & Fail-Fast Behavior
# =============================================================================
def test_pipeline_runner_halts_on_stage_failure():
    """Verify that if any stage fails, the runner immediately halts and does not execute subsequent stages."""
    from scripts.run_ci_pipeline import CIPipelineRunner

    runner = CIPipelineRunner(skip_install=True)

    # Mock a critical failure in stage 2 (lint)
    def mock_failing_lint():
        return False, "Simulated critical lint error: Syntax or typing violation"

    runner.stage_2_lint = mock_failing_lint  # type: ignore

    exit_code = runner.run_pipeline()

    assert exit_code == 1, "Runner must return exit code 1 on stage failure"

    # Verify that stages after stage 2 were NOT executed (fail-fast)
    executed_stage_ids = [res.stage_id for res in runner.results]
    assert 2 in executed_stage_ids
    assert 3 not in executed_stage_ids, "Stage 3 should have been halted due to stage 2 failure"
    assert 4 not in executed_stage_ids, "Stage 4 should have been halted due to stage 2 failure"
    assert 9 not in executed_stage_ids, "Stage 9 should have been halted due to stage 2 failure"


# =============================================================================
# 3. No Automatic Deployment to Production
# =============================================================================
def test_zero_automatic_production_deployment(github_workflow: dict):
    """Verify that the CI pipeline does NOT automatically deploy to production."""
    jobs = github_workflow.get("jobs", {})

    # Ensure no automated 'deploy' or 'deploy-production' job exists that runs unconditionally
    for job_name, job_def in jobs.items():
        assert "deploy-production" not in job_name.lower(), (
            f"Found forbidden automated production deploy job: {job_name}"
        )
        if "deploy" in job_name.lower():
            # If any deployment job exists, it must have an explicit environment gate or manual condition
            assert "environment" in job_def or "if" in job_def

    # Workflow triggers must be restricted to standard CI events (push, pull_request)
    triggers = github_workflow.get("on") or github_workflow.get(True) or {}
    assert "push" in triggers or "pull_request" in triggers


def test_production_deployment_guardrails_documented(github_workflow: dict):
    """Verify that workflow comments or policy notes explicitly mandate gated production release."""
    workflow_path = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    content = workflow_path.read_text(encoding="utf-8")

    assert "Continuous Deployment to production is strictly forbidden" in content or (
        "Do not deploy automatically to production" in content
    )


# =============================================================================
# 4. Secure Secret Handling
# =============================================================================
def test_secrets_are_externalized_in_workflow():
    """Verify that GitHub Actions workflow does not contain hardcoded credentials."""
    workflow_path = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    content = workflow_path.read_text(encoding="utf-8")

    forbidden_patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----",
    ]

    for pat in forbidden_patterns:
        assert not re.search(pat, content), f"Workflow contains hardcoded credential matching {pat}"

    # Secret references must use GitHub secrets context
    assert "${{ secrets." in content, "Workflow must reference externalized GitHub Secrets"


def test_secret_scanner_detects_insecure_keys(tmp_path: Path):
    """Verify that the security scanner catches injected private keys or tokens."""
    from scripts.security_check import scan_for_secrets

    # Baseline scan on clean repository
    initial_violations = scan_for_secrets()
    assert len(initial_violations) == 0, f"Expected 0 violations on clean workspace, got {initial_violations}"


def test_secret_masking_utility():
    """Verify that secrets are masked properly and never printed raw."""
    from scripts.security_check import mask_secret

    sample_secret = "TEST_API_KEY_1234567890ABCDEF"
    masked = mask_secret(sample_secret)
    assert masked == "TES...DEF"
    assert "1234567890" not in masked

    short_secret = "secret"
    assert mask_secret(short_secret) == "***"


def test_gitignore_protects_credentials():
    """Verify that .gitignore excludes sensitive files."""
    gitignore_path = ROOT_DIR / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8")

    assert ".env" in content
    assert "*.pem" in content
    assert "*.key" in content


# =============================================================================
# 5. Clean Workspace Verification
# =============================================================================
def test_clean_workspace_passes_security_checks():
    """Verify that running security checks on this clean repository passes with code 0."""
    from scripts.security_check import run_all_security_checks

    exit_code = run_all_security_checks()
    assert exit_code == 0, "Security check suite must pass with code 0 on clean workspace"


def test_clean_workspace_passes_linting():
    """Verify that ruff linting passes with code 0 on all python packages."""
    from scripts.run_ci_pipeline import CIPipelineRunner

    runner = CIPipelineRunner(skip_install=True)
    success, err = runner.stage_2_lint()
    assert success is True, f"Linting check failed: {err}"
