# LifeThread: AWS Infrastructure Deployment Guide (Module 36)

This document outlines the deployment prerequisites, environment topologies, secret bootstrapping, and operational runbooks for the LifeThread platform on Amazon Web Services (AWS).

---

## 1. Architectural Topology & Environments

LifeThread infrastructure is strictly separated across three isolated environments:

| Environment | Multi-AZ | NAT Gateways | Database Tier | Cache Tier | ECS Fargate Tasks | Log Retention | Deletion Protection |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Development** | 2 AZs | 1 (Cost-optimized) | `db.t4g.micro` (Single-AZ, 20GB) | `cache.t4g.micro` (1 node) | 1 task (256 CPU / 512MB) | 7 days | Disabled |
| **Staging** | 2 AZs | 1 | `db.t4g.small` (Multi-AZ, 30GB) | `cache.t4g.small` (2 nodes) | 2 tasks (512 CPU / 1GB) | 14 days | Disabled |
| **Production** | 3 AZs | 3 (Redundant) | `db.r6g.large` (Multi-AZ, 100GB-500GB) | `cache.m6g.large` (3 nodes) | 3-12 tasks (1024 CPU / 2GB) | 90 days (KMS Encrypted) | Enabled |

---

## 2. Deployment Prerequisites

Before initiating any infrastructure deployment:

1. **Install Tooling**:
   - [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) (`>= 2.15.0`)
   - [Terraform](https://developer.hashicorp.com/terraform/install) or [OpenTofu](https://opentofu.org/) (`>= 1.5.0`)
2. **AWS Account & IAM Permissions**:
   - Ensure you are authenticated with an IAM Role granting permissions to manage VPC, ECS, RDS, ElastiCache, Secrets Manager, KMS, and CloudWatch.
   - Recommended: Use AWS SSO or AWS IAM Identity Center:
     ```bash
     aws sso login --profile lifethread-admin
     export AWS_PROFILE=lifethread-admin
     ```
3. **Verify Bedrock Model Access**:
   - In AWS Console -> Amazon Bedrock -> Model access, verify that `Anthropic Claude 3.5 Sonnet`, `Anthropic Claude 3 Haiku`, and `Amazon Titan Embeddings G1 - Text` are enabled.

---

## 3. Remote State Backend Bootstrap

To ensure reproducible, team-safe deployments without race conditions or state corruption, configure S3 remote state with DynamoDB state locking:

```bash
# 1. Create S3 Bucket for Terraform State (Enable versioning and KMS encryption)
aws s3api create-bucket \
  --bucket lifethread-terraform-state-ACCOUNT_ID \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket lifethread-terraform-state-ACCOUNT_ID \
  --versioning-configuration Status=Enabled

# 2. Create DynamoDB Table for State Locking
aws dynamodb create-table \
  --table-name lifethread-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

Uncomment the `backend "s3"` block in `infrastructure/terraform/environments/<env>/main.tf` when ready to use remote state.

---

## 4. Secret Management & Externalization Policy

**CRITICAL SECURITY RULE: NEVER COMMIT CREDENTIALS OR PLAINTEXT PASSWORDS.**

- All passwords (PostgreSQL, Redis AUTH, JWT secret keys, MCP tokens) are automatically generated via Terraform's `random_password` provider and directly stored into AWS Secrets Manager encrypted with a Customer Managed KMS Key (CMK).
- ECS containers receive secrets via AWS Secrets Manager ARN JSON key pointers:
  ```hcl
  secrets = [
    {
      name      = "DB_PASSWORD"
      valueFrom = "${var.db_secret_arn}:password::"
    }
  ]
  ```
- Application code retrieves secrets through native environment bindings injected by the ECS agent at container start, preventing secret exposure in task definition declarations or source code.

---

## 5. Step-by-Step Deployment Instructions

### A. Deploying Development

```bash
cd infrastructure/terraform/environments/development

# 1. Initialize Terraform
terraform init

# 2. Create environment variables file from template
cp terraform.tfvars.example terraform.tfvars
# (Optionally edit container image or VPC CIDR in terraform.tfvars)

# 3. Plan deployment (Inspect planned changes)
terraform plan -out=tfplan.dev

# 4. Apply infrastructure safely
terraform apply tfplan.dev
```

### B. Deploying Staging

```bash
cd infrastructure/terraform/environments/staging
terraform init
cp terraform.tfvars.example terraform.tfvars
terraform plan -out=tfplan.staging
terraform apply tfplan.staging
```

### C. Deploying Production

```bash
cd infrastructure/terraform/environments/production
terraform init
cp terraform.tfvars.example terraform.tfvars

# Review strict multi-AZ configuration
terraform plan -out=tfplan.prod

# Production deployment requires peer approval in CI/CD pipeline
terraform apply tfplan.prod
```

---

## 6. Verifying Deployment & Health Checks

Once `terraform apply` finishes:

1. Obtain the ALB DNS address from output:
   ```bash
   terraform output alb_dns_name
   ```
2. Verify application health probe:
   ```bash
   curl -I http://$(terraform output -raw alb_dns_name)/health/live
   # Expect HTTP/1.1 200 OK
   ```
3. Verify readiness probe:
   ```bash
   curl http://$(terraform output -raw alb_dns_name)/health/ready
   # Expect {"status":"ready","database":"connected","redis":"connected"}
   ```
4. View CloudWatch Dashboard:
   - Navigate to AWS CloudWatch -> Dashboards -> `lifethread-production-overview`
   - Monitor real-time request volume, latency, ECS container CPU/memory, RDS connections, and Bedrock token usage.

---

## 7. Disaster Recovery & Rollback Runbook

### Rollback Container Image
If an application release causes errors:
1. Update `container_image` in `terraform.tfvars` back to the previous stable release tag (e.g., `v0.9.9`).
2. Run `terraform apply -target=module.application`.
3. ECS will execute a rolling blue/green replacement with zero downtime.

### Database Snapshot Restore
In the event of catastrophic data corruption:
1. List available automated snapshots:
   ```bash
   aws rds describe-db-snapshots --db-instance-identifier lifethread-production-db
   ```
2. Restore to a new point-in-time instance:
   ```bash
   aws rds restore-db-instance-to-point-in-time \
     --source-db-instance-identifier lifethread-production-db \
     --target-db-instance-identifier lifethread-production-db-restored \
     --restore-time "2026-09-26T00:00:00Z"
   ```
