output "redis_endpoint" {
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  description = "Primary endpoint address of the Redis replication group"
}

output "redis_port" {
  value       = aws_elasticache_replication_group.redis.port
  description = "Redis listening port"
}

output "redis_replication_group_id" {
  value       = aws_elasticache_replication_group.redis.id
  description = "ID of the Redis replication group"
}
