variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for S3 storage encryption"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
