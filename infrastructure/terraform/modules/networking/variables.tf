variable "project_name" {
  type        = string
  description = "Project name prefix for all network resources"
  default     = "lifethread"
}

variable "environment" {
  type        = string
  description = "Target deployment environment (development, staging, production)"
}

variable "vpc_cidr" {
  type        = string
  description = "Base CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "List of AWS availability zones for multi-AZ topology"
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for public subnets (ALB & NAT Gateways)"
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "app_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private application subnets (ECS tasks)"
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "data_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for isolated data subnets (RDS PostgreSQL & ElastiCache)"
  default     = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
}

variable "single_nat_gateway" {
  type        = bool
  description = "Whether to use a single NAT Gateway (true for dev/staging cost savings, false for prod high availability)"
  default     = true
}

variable "app_port" {
  type        = number
  description = "Application listening port for ECS tasks"
  default     = 8000
}

variable "tags" {
  type        = map(string)
  description = "Resource tags applied to all networking resources"
  default     = {}
}
