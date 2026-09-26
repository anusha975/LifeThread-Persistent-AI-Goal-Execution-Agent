output "app_log_group_name" {
  value       = aws_cloudwatch_log_group.app.name
  description = "Name of the application CloudWatch log group"
}

output "app_log_group_arn" {
  value       = aws_cloudwatch_log_group.app.arn
  description = "ARN of the application CloudWatch log group"
}

output "alerts_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "ARN of the SNS alerts topic"
}

output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.main.dashboard_name
  description = "Name of the CloudWatch dashboard"
}
