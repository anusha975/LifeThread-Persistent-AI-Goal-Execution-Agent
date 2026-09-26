# =============================================================================
# LifeThread Infrastructure: Development Environment
# Cost-optimized single-NAT, lightweight database/cache, fast iteration setup
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

  # Production S3 backend with DynamoDB locking configured in root or CI/CD
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

# 1. Secrets & KMS Encryption
module "secrets" {
  source = "../../modules/secrets"

  project_name = var.project_name
  environment  = var.environment
  db_username  = "lifethread_dev"
}

# 2. Networking
module "networking" {
  source = "../../modules/networking"

  project_name        = var.project_name
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  public_subnet_cidrs = ["10.10.1.0/24", "10.10.2.0/24"]
  app_subnet_cidrs    = ["10.10.11.0/24", "10.10.12.0/24"]
  data_subnet_cidrs   = ["10.10.21.0/24", "10.10.22.0/24"]
  single_nat_gateway  = true
}

# 3. PostgreSQL Database
module "database" {
  source = "../../modules/database"

  project_name            = var.project_name
  environment             = var.environment
  subnet_ids              = module.networking.data_subnet_ids
  security_group_id       = module.networking.db_security_group_id
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  max_allocated_storage   = 50
  multi_az                = false
  backup_retention_period = 3
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
  node_type          = "cache.t4g.micro"
  num_cache_clusters = 1
  auth_token         = module.secrets.redis_auth_token
  kms_key_arn        = module.secrets.kms_key_arn
}

# 5. AI Services & Bedrock IAM
module "ai_services" {
  source = "../../modules/ai_services"

  project_name = var.project_name
  environment  = var.environment
  kms_key_arn  = module.secrets.kms_key_arn
}

# 6. Monitoring & Logs
module "monitoring" {
  source = "../../modules/monitoring"

  project_name            = var.project_name
  environment             = var.environment
  log_retention_days      = 7
  kms_key_arn             = module.secrets.kms_key_arn
  ecs_cluster_name        = module.application.ecs_cluster_name
  ecs_service_name        = module.application.ecs_service_name
  alb_arn_suffix          = module.application.alb_arn
  target_group_arn_suffix = module.application.target_group_arn
  db_instance_id          = module.database.db_instance_id
}

# 7. Application ECS Fargate Service
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
  cpu                     = 256
  memory                  = 512
  desired_count           = 1
  min_capacity            = 1
  max_capacity            = 2

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
