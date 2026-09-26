output "alb_dns_name" {
  value       = module.application.alb_dns_name
  description = "Public URL of the LifeThread Production API"
}

output "vpc_id" {
  value       = module.networking.vpc_id
  description = "Production VPC ID"
}

output "db_endpoint" {
  value       = module.database.db_endpoint
  description = "Production Database endpoint"
}

output "redis_endpoint" {
  value       = module.redis.redis_endpoint
  description = "Production Redis endpoint"
}

output "dashboard_name" {
  value       = module.monitoring.dashboard_name
  description = "Production CloudWatch overview dashboard"
}

output "alerts_topic_arn" {
  value       = module.monitoring.alerts_topic_arn
  description = "Production SNS topic for operational alerting"
}
