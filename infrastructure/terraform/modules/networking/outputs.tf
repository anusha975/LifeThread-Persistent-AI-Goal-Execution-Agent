output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the VPC"
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "List of IDs of public subnets"
}

output "app_subnet_ids" {
  value       = aws_subnet.app[*].id
  description = "List of IDs of private application subnets"
}

output "data_subnet_ids" {
  value       = aws_subnet.data[*].id
  description = "List of IDs of isolated data subnets"
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "Security group ID for the Application Load Balancer"
}

output "app_security_group_id" {
  value       = aws_security_group.app.id
  description = "Security group ID for ECS application containers"
}

output "db_security_group_id" {
  value       = aws_security_group.database.id
  description = "Security group ID for RDS PostgreSQL"
}

output "redis_security_group_id" {
  value       = aws_security_group.redis.id
  description = "Security group ID for ElastiCache Redis"
}
