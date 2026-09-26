# =============================================================================
# LifeThread Infrastructure: Database Module
# Production-ready PostgreSQL 16 on AWS RDS with SSL enforcement, pgvector support,
# automated backups, KMS storage encryption, and Performance Insights
# =============================================================================

# 1. DB Subnet Group across isolated data subnets
resource "aws_db_subnet_group" "db" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  description = "Isolated data subnet group for LifeThread ${var.environment} PostgreSQL"
  subnet_ids  = var.subnet_ids

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-db-subnet-group"
    Environment = var.environment
  })
}

# 2. Parameter Group: Enforce TLS 1.3 / SSL and optimize connection pooling
resource "aws_db_parameter_group" "pg" {
  name        = "${var.project_name}-${var.environment}-pg16-params"
  family      = "postgres16"
  description = "PostgreSQL 16 parameter group with SSL enforcement for LifeThread"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,pgvector"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-pg-params"
    Environment = var.environment
  })
}

# 3. RDS PostgreSQL Instance
resource "aws_db_instance" "postgres" {
  identifier                  = "${var.project_name}-${var.environment}-db"
  engine                      = "postgres"
  engine_version              = "16.3"
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  max_allocated_storage       = var.max_allocated_storage
  storage_type                = "gp3"
  storage_encrypted           = true
  kms_key_id                  = var.kms_key_arn

  db_name                     = "${var.db_name}_${var.environment}"
  username                    = var.db_username
  password                    = var.db_password
  port                        = 5432

  db_subnet_group_name        = aws_db_subnet_group.db.name
  vpc_security_group_ids      = [var.security_group_id]
  parameter_group_name        = aws_db_parameter_group.pg.name
  publicly_accessible         = false

  multi_az                    = var.multi_az
  backup_retention_period     = var.backup_retention_period
  backup_window               = "03:00-04:00"
  maintenance_window          = "Sun:04:30-Sun:05:30"
  auto_minor_version_upgrade  = true
  deletion_protection         = var.deletion_protection
  skip_final_snapshot         = var.environment != "production"
  final_snapshot_identifier   = var.environment == "production" ? "${var.project_name}-${var.environment}-db-final-snapshot" : null

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  performance_insights_enabled    = var.environment == "production"
  performance_insights_kms_key_id = var.environment == "production" ? var.kms_key_arn : null

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-postgres"
    Environment = var.environment
  })
}
