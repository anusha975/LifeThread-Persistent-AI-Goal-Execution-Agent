# =============================================================================
# LifeThread Infrastructure: Staging Environment
# Pre-production validation environment mirroring production architecture
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

  # backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# 1. Secrets & KMS
module "secrets" {
  source = "../../modules/secrets"

  project_name = var.project_name
  environment  = var.environment
  db_username  = "lifethread_staging"
}

# 2. Networking
module "networking" {
  source = "../../modules/networking"

  project_name        = var.project_name
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  public_subnet_cidrs = ["10.20.1.0/24", "10.20.2.0/24"]
  app_subnet_cidrs    = ["10.20.11.0/24", "10.20.12.0/24"]
  data_subnet_cidrs   = ["10.20.21.0/24", "10.20.22.0/24"]
  single_nat_gateway  = true
}

# 3. PostgreSQL Database
module "database" {
  source = "../../modules/database"

  project_name            = var.project_name
  environment             = var.environment
  subnet_ids              = module.networking.data_subnet_ids
  security_group_id       = module.networking.db_security_group_id
  instance_class          = "db.t4g.small"
  allocated_storage       = 30
  max_allocated_storage   = 100
  multi_az                = true
  backup_retention_period = 7
  deletion_protection     = false
  db_name                 = "lifethread"
  db_username             = module.secrets.db_username
  db_password             = module.secrets.db_password
  kms_key_arn             = module.secrets.kms_key_arn
}

# 4. Redis Cache
module "redis" {
  source = "../../modules/redis"

  project_name       = var.project_name
  environment        = var.environment
  subnet_ids         = module.networking.data_subnet_ids
  security_group_id  = module.networking.redis_security_group_id
  node_type          = "cache.t4g.small"
  num_cache_clusters = 2
  auth_token         = module.secrets.redis_auth_token
  kms_key_arn        = module.secrets.kms_key_arn
}

# 5. AI Services
module "ai_services" {
  source = "../../modules/ai_services"

  project_name = var.project_name
  environment  = var.environment
  kms_key_arn  = module.secrets.kms_key_arn
}

# 6. Monitoring
module "monitoring" {
  source = "../../modules/monitoring"

  project_name            = var.project_name
  environment             = var.environment
  log_retention_days      = 14
  kms_key_arn             = module.secrets.kms_key_arn
  ecs_cluster_name        = module.application.ecs_cluster_name
  ecs_service_name        = module.application.ecs_service_name
  alb_arn_suffix          = module.application.alb_arn
  target_group_arn_suffix = module.application.target_group_arn
  db_instance_id          = module.database.db_instance_id
}

# 7. Application Service
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
  cpu                     = 512
  memory                  = 1024
  desired_count           = 2
  min_capacity            = 1
  max_capacity            = 4

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
