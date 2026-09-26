variable "project_name" {
  type        = string
  description = "Project name prefix"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "db_username" {
  type        = string
  description = "PostgreSQL master username"
  default     = "lifethread_admin"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
