# =============================================================================
# LifeThread Infrastructure: Production Environment
# High-Availability Multi-AZ Architecture, Automated Failover, Deletion Protection,
# Pinned Immutable Container Releases, and Comprehensive SLA Observability
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Production state backend: Locked with DynamoDB and encrypted with S3 bucket KMS key
  # backend "s3" {
  #   bucket         = "lifethread-production-tfstate"
  #   key            = "production/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "lifethread-production-tflocks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      Tier        = "mission-critical"
      ManagedBy   = "terraform"
    }
  }
}

# 1. Production Secrets & Customer-Managed KMS Key (30-day recovery window)
module "secrets" {
  source = "../../modules/secrets"

  project_name = var.project_name
  environment  = var.environment
  db_username  = "lifethread_master"
}

# 2. Production Networking across 3 Availability Zones with Redundant Multi-NAT Gateways
module "networking" {
  source = "../../modules/networking"

  project_name        = var.project_name
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  app_subnet_cidrs    = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  data_subnet_cidrs   = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
  single_nat_gateway  = false # True Multi-AZ NAT redundancy
}

# 3. Production PostgreSQL 16 (Multi-AZ with Auto-scaling GP3 Storage and 30-day backups)
module "database" {
  source = "../../modules/database"

  project_name            = var.project_name
  environment             = var.environment
  subnet_ids              = module.networking.data_subnet_ids
  security_group_id       = module.networking.db_security_group_id
  instance_class          = "db.r6g.large"
  allocated_storage       = 100
  max_allocated_storage   = 500
  multi_az                = true
  backup_retention_period = 30
  deletion_protection     = true
  db_name                 = "lifethread"
  db_username             = module.secrets.db_username
  db_password             = module.secrets.db_password
  kms_key_arn             = module.secrets.kms_key_arn
}

# 4. Production Redis (Multi-Node Cluster with Automated Failover and In-transit TLS)
module "redis" {
  source = "../../modules/redis"

  project_name       = var.project_name
  environment        = var.environment
  subnet_ids         = module.networking.data_subnet_ids
  security_group_id  = module.networking.redis_security_group_id
  node_type          = "cache.m6g.large"
  num_cache_clusters = 3
  auth_token         = module.secrets.redis_auth_token
  kms_key_arn        = module.secrets.kms_key_arn
}

# 5. Production AI Services (Bedrock IAM + Context Strands Storage)
module "ai_services" {
  source = "../../modules/ai_services"

  project_name = var.project_name
  environment  = var.environment
  kms_key_arn  = module.secrets.kms_key_arn
}

# 6. Production Monitoring (90-day retention, PagerDuty/SNS alerts, metric alarms)
module "monitoring" {
  source = "../../modules/monitoring"

  project_name            = var.project_name
  environment             = var.environment
  log_retention_days      = 90
  kms_key_arn             = module.secrets.kms_key_arn
  ecs_cluster_name        = module.application.ecs_cluster_name
  ecs_service_name        = module.application.ecs_service_name
  alb_arn_suffix          = module.application.alb_arn
  target_group_arn_suffix = module.application.target_group_arn
  db_instance_id          = module.database.db_instance_id
}

# 7. Production Application Service (High CPU/Memory, 3 to 12 Auto-Scaling Tasks)
module "application" {
  source = "../../modules/application"

  project_name            = var.project_name
  environment             = var.environment
  vpc_id                  = module.networking.vpc_id
  public_subnet_ids       = module.networking.public_subnet_ids
  app_subnet_ids          = module.networking.app_subnet_ids
  alb_security_group_id   = module.networking.alb_security_group_id
  app_security_group_id   = module.networking.app_security_group_id
  container_image         = var.container_image
  cpu                     = 1024
  memory                  = 2048
  desired_count           = 3
  min_capacity            = 3
  max_capacity            = 12

  db_host                 = module.database.db_address
  db_port                 = module.database.db_port
  db_name                 = module.database.db_name
  db_secret_arn           = module.secrets.db_secret_arn
  app_security_secret_arn = module.secrets.app_security_secret_arn
  redis_endpoint          = module.redis.redis_endpoint
  redis_port              = module.redis.redis_port
  redis_secret_arn        = module.secrets.redis_secret_arn
  bedrock_policy_arn      = module.ai_services.bedrock_policy_arn
  kms_key_arn             = module.secrets.kms_key_arn
  log_group_name          = module.monitoring.app_log_group_name
}
