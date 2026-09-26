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
  description = "Security group ID for Redis"
}

variable "node_type" {
  type        = string
  description = "ElastiCache node type (e.g. cache.t4g.micro for dev, cache.m6g.large for prod)"
  default     = "cache.t4g.micro"
}

variable "num_cache_clusters" {
  type        = number
  description = "Number of cache clusters (1 for dev, 2+ for prod with failover)"
  default     = 1
}

variable "auth_token" {
  type        = string
  sensitive   = true
  description = "Redis authentication token"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for encryption at rest"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
