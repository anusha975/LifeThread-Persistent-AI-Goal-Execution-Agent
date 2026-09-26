import re
from pathlib import Path

INFRA_ROOT = Path(__file__).resolve().parent.parent.parent / "infrastructure" / "terraform"
DEPLOYMENT_DOC = Path(__file__).resolve().parent.parent.parent / "infrastructure" / "DEPLOYMENT.md"


def test_infrastructure_directory_structure_exists():
    """Verify standard modules and environment directories exist."""
    assert INFRA_ROOT.exists(), f"Infrastructure directory not found at {INFRA_ROOT}"

    required_modules = [
        "networking",
        "database",
        "redis",
        "ai_services",
        "secrets",
        "application",
        "monitoring",
    ]
    for mod in required_modules:
        mod_dir = INFRA_ROOT / "modules" / mod
        assert mod_dir.is_dir(), f"Missing module directory: {mod_dir}"
        assert (mod_dir / "main.tf").is_file(), f"Missing main.tf in module {mod}"
        assert (mod_dir / "variables.tf").is_file(), f"Missing variables.tf in module {mod}"
        assert (mod_dir / "outputs.tf").is_file(), f"Missing outputs.tf in module {mod}"

    required_envs = ["development", "staging", "production"]
    for env in required_envs:
        env_dir = INFRA_ROOT / "environments" / env
        assert env_dir.is_dir(), f"Missing environment directory: {env_dir}"
        assert (env_dir / "main.tf").is_file(), f"Missing main.tf in environment {env}"
        assert (env_dir / "variables.tf").is_file(), f"Missing variables.tf in environment {env}"
        assert (env_dir / "outputs.tf").is_file(), f"Missing outputs.tf in environment {env}"
        assert (env_dir / "terraform.tfvars.example").is_file(), f"Missing tfvars example in {env}"


def test_zero_hardcoded_credentials_in_terraform():
    """Audit all Terraform files to guarantee no committed secrets or raw AWS access keys."""
    # Pattern detecting AWS access keys, private keys, or raw hardcoded passwords
    aws_key_pattern = re.compile(r"AKIA[0-9A-Z]{16}")
    private_key_pattern = re.compile(r"-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----")
    raw_secret_pattern = re.compile(r'(password|secret_key|api_key)\s*=\s*"[A-Za-z0-9!@#$%^&*()_+]{8,}"')

    tf_files = list(INFRA_ROOT.glob("**/*.tf")) + list(INFRA_ROOT.glob("**/*.tfvars.example"))
    assert len(tf_files) >= 20, "Expected at least 20 terraform configuration files"

    for f in tf_files:
        content = f.read_text(encoding="utf-8")
        assert not aws_key_pattern.search(content), f"Hardcoded AWS key detected in {f}"
        assert not private_key_pattern.search(content), f"Private key detected in {f}"

        # Ensure passwords are not hardcoded plaintext (allow placeholders like CHANGEME_BOOTSTRAP_VALUE)
        for match in raw_secret_pattern.finditer(content):
            matched_line = match.group(0)
            assert (
                "CHANGEME" in matched_line
                or "random_password" in matched_line
                or "var." in matched_line
            ), f"Potential hardcoded secret in {f}: {matched_line}"


def test_environment_separation_and_topology():
    """Verify distinct parameterization between development, staging, and production."""
    dev_main = (INFRA_ROOT / "environments" / "development" / "main.tf").read_text(encoding="utf-8")
    staging_main = (INFRA_ROOT / "environments" / "staging" / "main.tf").read_text(encoding="utf-8")
    prod_main = (INFRA_ROOT / "environments" / "production" / "main.tf").read_text(encoding="utf-8")

    # 1. Database scaling differences
    assert 'instance_class          = "db.t4g.micro"' in dev_main
    assert 'instance_class          = "db.t4g.small"' in staging_main
    assert 'instance_class          = "db.r6g.large"' in prod_main

    # 2. Multi-AZ and failover differences
    assert "multi_az                = false" in dev_main
    assert "multi_az                = true" in prod_main
    assert "single_nat_gateway  = true" in dev_main
    assert "single_nat_gateway  = false" in prod_main

    # 3. Deletion protection
    assert "deletion_protection     = false" in dev_main
    assert "deletion_protection     = true" in prod_main

    # 4. Log retention policies
    assert "log_retention_days      = 7" in dev_main
    assert "log_retention_days      = 14" in staging_main
    assert "log_retention_days      = 90" in prod_main


def test_secrets_externalization_and_kms_encryption():
    """Verify secrets module uses random_password generation and KMS Customer Managed Keys."""
    secrets_main = (INFRA_ROOT / "modules" / "secrets" / "main.tf").read_text(encoding="utf-8")

    assert "resource \"aws_kms_key\" \"secrets\"" in secrets_main
    assert "enable_key_rotation     = true" in secrets_main
    assert "resource \"random_password\" \"db_password\"" in secrets_main
    assert "resource \"random_password\" \"jwt_secret_key\"" in secrets_main
    assert "resource \"aws_secretsmanager_secret\" \"database\"" in secrets_main
    assert "resource \"aws_secretsmanager_secret\" \"app_security\"" in secrets_main
    assert "resource \"aws_secretsmanager_secret\" \"redis\"" in secrets_main


def test_ecs_fargate_task_definition_uses_secret_injection():
    """Verify ECS container tasks inject secrets from Secrets Manager without exposing plaintext."""
    app_main = (INFRA_ROOT / "modules" / "application" / "main.tf").read_text(encoding="utf-8")

    assert "secrets = [" in app_main
    assert "valueFrom = \"${var.db_secret_arn}:username::\"" in app_main
    assert "valueFrom = \"${var.db_secret_arn}:password::\"" in app_main
    assert "valueFrom = \"${var.app_security_secret_arn}:jwt_secret_key::\"" in app_main
    assert "requires_compatibilities = [\"FARGATE\"]" in app_main


def test_database_module_enforces_ssl_and_pgvector():
    """Verify RDS configuration enforces SSL and enables pgvector extension for AI search."""
    db_main = (INFRA_ROOT / "modules" / "database" / "main.tf").read_text(encoding="utf-8")

    assert "name  = \"rds.force_ssl\"" in db_main
    assert "value = \"1\"" in db_main
    assert "pgvector" in db_main
    assert "storage_encrypted           = true" in db_main


def test_redis_module_enforces_encryption_and_auth():
    """Verify ElastiCache Redis configuration enforces TLS in-transit and auth token."""
    redis_main = (INFRA_ROOT / "modules" / "redis" / "main.tf").read_text(encoding="utf-8")

    assert "transit_encryption_enabled = true" in redis_main
    assert "at_rest_encryption_enabled = true" in redis_main
    assert "auth_token                 = var.auth_token" in redis_main


def test_ai_services_module_configures_bedrock_iam_and_strands_s3():
    """Verify AI services module configures Bedrock permissions and S3 storage with KMS."""
    ai_main = (INFRA_ROOT / "modules" / "ai_services" / "main.tf").read_text(encoding="utf-8")

    assert "bedrock:InvokeModel" in ai_main
    assert "bedrock:Converse" in ai_main
    assert "bedrock:InvokeAgent" in ai_main
    assert "bedrock:Retrieve" in ai_main
    assert "resource \"aws_s3_bucket\" \"strands\"" in ai_main
    assert "block_public_acls       = true" in ai_main


def test_monitoring_module_configures_metric_alarms_and_dashboard():
    """Verify CloudWatch alarms and dashboard are configured for platform observability."""
    mon_main = (INFRA_ROOT / "modules" / "monitoring" / "main.tf").read_text(encoding="utf-8")

    assert "resource \"aws_cloudwatch_metric_alarm\" \"ecs_high_cpu\"" in mon_main
    assert "resource \"aws_cloudwatch_metric_alarm\" \"ecs_high_mem\"" in mon_main
    assert "resource \"aws_cloudwatch_metric_alarm\" \"alb_5xx\"" in mon_main
    assert "resource \"aws_cloudwatch_metric_alarm\" \"rds_low_storage\"" in mon_main
    assert "resource \"aws_cloudwatch_dashboard\" \"main\"" in mon_main
    assert "resource \"aws_sns_topic\" \"alerts\"" in mon_main


def test_deployment_documentation_completeness():
    """Verify deployment guide documents prerequisites, remote state, secret bootstrapping, and runbooks."""
    assert DEPLOYMENT_DOC.is_file(), "DEPLOYMENT.md missing"
    doc_text = DEPLOYMENT_DOC.read_text(encoding="utf-8")

    assert "Deployment Prerequisites" in doc_text
    assert "Remote State Backend Bootstrap" in doc_text
    assert "Secret Management & Externalization Policy" in doc_text
    assert "Deploying Development" in doc_text
    assert "Deploying Staging" in doc_text
    assert "Deploying Production" in doc_text
    assert "Disaster Recovery & Rollback Runbook" in doc_text
