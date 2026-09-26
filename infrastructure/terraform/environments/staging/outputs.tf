output "alb_dns_name" {
  value       = module.application.alb_dns_name
  description = "Public URL of the LifeThread Staging API"
}

output "vpc_id" {
  value       = module.networking.vpc_id
  description = "VPC ID"
}

output "db_endpoint" {
  value       = module.database.db_endpoint
  description = "Database connection endpoint"
}

output "redis_endpoint" {
  value       = module.redis.redis_endpoint
  description = "Redis endpoint"
}

output "dashboard_name" {
  value       = module.monitoring.dashboard_name
  description = "CloudWatch overview dashboard"
}
