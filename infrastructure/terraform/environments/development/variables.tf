variable "aws_region" {
  type        = string
  description = "AWS deployment region"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment identifier"
  default     = "development"
}

variable "project_name" {
  type        = string
  description = "Project name"
  default     = "lifethread"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block"
  default     = "10.10.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "Availability zones"
  default     = ["us-east-1a", "us-east-1b"]
}

variable "container_image" {
  type        = string
  description = "Container image URI"
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/lifethread-backend:dev-latest"
}
