variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the ALB"
}

variable "app_subnet_ids" {
  type        = list(string)
  description = "Private application subnet IDs for ECS tasks"
}

variable "alb_security_group_id" {
  type        = string
  description = "ALB security group ID"
}

variable "app_security_group_id" {
  type        = string
  description = "ECS app security group ID"
}

variable "container_image" {
  type        = string
  description = "Docker image URI for the backend container"
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/lifethread-backend:latest"
}

variable "container_port" {
  type        = number
  description = "Container port"
  default     = 8000
}

variable "cpu" {
  type        = number
  description = "Fargate CPU units (256, 512, 1024, etc.)"
  default     = 512
}

variable "memory" {
  type        = number
  description = "Fargate Memory in MB (1024, 2048, 4096, etc.)"
  default     = 1024
}

variable "desired_count" {
  type        = number
  description = "Desired number of running ECS tasks"
  default     = 2
}

variable "min_capacity" {
  type        = number
  description = "Auto-scaling minimum task count"
  default     = 1
}

variable "max_capacity" {
  type        = number
  description = "Auto-scaling maximum task count"
  default     = 6
}

variable "db_host" {
  type        = string
  description = "PostgreSQL hostname"
}

variable "db_port" {
  type        = number
  description = "PostgreSQL port"
  default     = 5432
}

variable "db_name" {
  type        = string
  description = "Database name"
}

variable "db_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for database credentials"
}

variable "app_security_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for app security (JWT & internal tokens)"
}

variable "redis_endpoint" {
  type        = string
  description = "Redis endpoint host"
}

variable "redis_port" {
  type        = number
  description = "Redis port"
  default     = 6379
}

variable "redis_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for Redis credentials"
}

variable "bedrock_policy_arn" {
  type        = string
  description = "IAM policy ARN for Bedrock access"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for secret decryption"
}

variable "log_group_name" {
  type        = string
  description = "CloudWatch log group name for application logs"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
