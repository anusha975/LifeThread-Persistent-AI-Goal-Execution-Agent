variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of isolated data subnet IDs"
}

variable "security_group_id" {
  type        = string
  description = "Security group ID for database access"
}

variable "instance_class" {
  type        = string
  description = "RDS instance class (e.g. db.t4g.micro for dev, db.r6g.large for prod)"
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  type        = number
  description = "Allocated storage in GB"
  default     = 20
}

variable "max_allocated_storage" {
  type        = number
  description = "Maximum auto-scaling storage threshold in GB"
  default     = 100
}

variable "multi_az" {
  type        = bool
  description = "Enable Multi-AZ deployment for failover"
  default     = false
}

variable "backup_retention_period" {
  type        = number
  description = "Backup retention days"
  default     = 7
}

variable "deletion_protection" {
  type        = bool
  description = "Prevent accidental database deletion"
  default     = false
}

variable "db_name" {
  type        = string
  description = "Initial database name"
  default     = "lifethread"
}

variable "db_username" {
  type        = string
  description = "Master database username"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Master database password"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for storage encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
