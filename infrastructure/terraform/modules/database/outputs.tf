output "db_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "Connection endpoint for PostgreSQL (host:port)"
}

output "db_address" {
  value       = aws_db_instance.postgres.address
  description = "Hostname of the PostgreSQL instance"
}

output "db_port" {
  value       = aws_db_instance.postgres.port
  description = "PostgreSQL listening port"
}

output "db_name" {
  value       = aws_db_instance.postgres.db_name
  description = "Name of the default PostgreSQL database"
}

output "db_instance_id" {
  value       = aws_db_instance.postgres.identifier
  description = "RDS DB instance identifier"
}

output "db_resource_id" {
  value       = aws_db_instance.postgres.resource_id
  description = "Resource ID used for CloudWatch and Performance Insights"
}
