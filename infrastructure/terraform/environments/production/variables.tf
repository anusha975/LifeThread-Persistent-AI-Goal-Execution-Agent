variable "aws_region" {
  type        = string
  description = "AWS deployment region"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment identifier"
  default     = "production"
}

variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "High-availability 3-AZ topology"
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "container_image" {
  type        = string
  description = "Immutable pinned release container image URI"
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/lifethread-backend:v1.0.0"
}
