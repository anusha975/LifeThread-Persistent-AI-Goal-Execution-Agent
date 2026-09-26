variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days (e.g. 7 for dev, 30 for staging, 90 for prod)"
  default     = 30
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for log encryption"
}

variable "ecs_cluster_name" {
  type        = string
  description = "Name of the ECS cluster"
}

variable "ecs_service_name" {
  type        = string
  description = "Name of the ECS service"
}

variable "alb_arn_suffix" {
  type        = string
  description = "ARN suffix of the ALB for CloudWatch metrics"
}

variable "target_group_arn_suffix" {
  type        = string
  description = "ARN suffix of the target group for CloudWatch metrics"
}

variable "db_instance_id" {
  type        = string
  description = "RDS DB instance identifier"
}

variable "alert_email" {
  type        = string
  description = "Operational alert email for SNS notifications"
  default     = "alerts@example.com"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
