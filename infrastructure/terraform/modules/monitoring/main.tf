# =============================================================================
# LifeThread Infrastructure: Monitoring & Observability Module
# CloudWatch Log Groups with KMS Encryption, Metric Alarms (ALB, ECS, RDS, Redis, Bedrock),
# Operational Dashboard, and SNS Alert Topic
# =============================================================================

# 1. CloudWatch Log Group for Application Containers
resource "aws_cloudwatch_log_group" "app" {
  name              = "/lifethread/${var.environment}/backend"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-app-logs"
    Environment = var.environment
  })
}

# CloudWatch Log Group for Bedrock AI Invocations & Agent Traces
resource "aws_cloudwatch_log_group" "bedrock" {
  name              = "/lifethread/${var.environment}/bedrock-ai"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-bedrock-logs"
    Environment = var.environment
  })
}

# 2. SNS Alert Topic for Operational Notifications
resource "aws_sns_topic" "alerts" {
  name              = "${var.project_name}-${var.environment}-alerts"
  kms_master_key_id = var.kms_key_arn

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-alerts"
    Environment = var.environment
  })
}

# 3. Metric Alarm: ECS High CPU Utilization (> 85%)
resource "aws_cloudwatch_metric_alarm" "ecs_high_cpu" {
  alarm_name          = "${var.project_name}-${var.environment}-ecs-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Triggers when ECS container CPU exceeds 85% for 3 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.tags
}

# 4. Metric Alarm: ECS High Memory Utilization (> 90%)
resource "aws_cloudwatch_metric_alarm" "ecs_high_mem" {
  alarm_name          = "${var.project_name}-${var.environment}-ecs-high-memory"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 90
  alarm_description   = "Triggers when ECS container Memory exceeds 90% for 3 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.tags
}

# 5. Metric Alarm: ALB 5XX High Error Rate
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.project_name}-${var.environment}-alb-high-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Triggers when application returns more than 10 5XX errors within 2 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  tags = var.tags
}

# 6. Metric Alarm: RDS Low Storage Space (< 5GB)
resource "aws_cloudwatch_metric_alarm" "rds_low_storage" {
  alarm_name          = "${var.project_name}-${var.environment}-rds-low-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120 # 5 GB in bytes
  alarm_description   = "Triggers when PostgreSQL free storage falls below 5GB"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = var.db_instance_id
  }

  tags = var.tags
}

# 7. CloudWatch Operational Dashboard
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-${var.environment}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", period = 60 }],
            [".", "TargetResponseTime", ".", ".", { stat = "Average", period = 60 }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "ALB Request Volume & Latency"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", var.ecs_service_name, "ClusterName", var.ecs_cluster_name, { stat = "Average" }],
            [".", "MemoryUtilization", ".", ".", ".", ".", { stat = "Average" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "ECS Fargate Resource Utilization"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id, { stat = "Average" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Average" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "RDS PostgreSQL Health & Connections"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "Invocations", { stat = "Sum" }],
            [".", "InvocationThrottles", { stat = "Sum" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "Amazon Bedrock Invocations & Throttles"
        }
      }
    ]
  })
}
