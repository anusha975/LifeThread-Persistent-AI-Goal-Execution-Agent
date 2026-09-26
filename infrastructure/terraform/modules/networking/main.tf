# =============================================================================
# LifeThread Infrastructure: Networking Module
# Multi-AZ VPC, Tiered Subnets (Public, Private App, Isolated Data), & Security Groups
# =============================================================================

# 1. Virtual Private Cloud (VPC)
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-vpc"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

# 2. Internet Gateway
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-igw"
    Environment = var.environment
  })
}

# 3. Public Subnets (ALB & NAT Gateways)
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-public-${var.availability_zones[count.index]}"
    Tier        = "public"
    Environment = var.environment
  })
}

# 4. Private Application Subnets (ECS Fargate Tasks)
resource "aws_subnet" "app" {
  count             = length(var.app_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.app_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-app-${var.availability_zones[count.index]}"
    Tier        = "application"
    Environment = var.environment
  })
}

# 5. Private Isolated Data Subnets (RDS PostgreSQL & ElastiCache Redis)
resource "aws_subnet" "data" {
  count             = length(var.data_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.data_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-data-${var.availability_zones[count.index]}"
    Tier        = "data-isolated"
    Environment = var.environment
  })
}

# 6. Elastic IPs & NAT Gateways
resource "aws_eip" "nat" {
  count  = var.single_nat_gateway ? 1 : length(var.public_subnet_cidrs)
  domain = "vpc"

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-nat-eip-${count.index + 1}"
    Environment = var.environment
  })
}

resource "aws_nat_gateway" "nat" {
  count         = var.single_nat_gateway ? 1 : length(var.public_subnet_cidrs)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-nat-${count.index + 1}"
    Environment = var.environment
  })

  depends_on = [aws_internet_gateway.igw]
}

# 7. Route Tables & Associations
# Public Route Table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-public-rt"
    Environment = var.environment
  })
}

resource "aws_route_table_association" "public" {
  count          = length(var.public_subnet_cidrs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Application Private Route Tables (routed through NAT)
resource "aws_route_table" "app" {
  count  = var.single_nat_gateway ? 1 : length(var.app_subnet_cidrs)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = var.single_nat_gateway ? aws_nat_gateway.nat[0].id : aws_nat_gateway.nat[count.index].id
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-app-rt-${count.index + 1}"
    Environment = var.environment
  })
}

resource "aws_route_table_association" "app" {
  count          = length(var.app_subnet_cidrs)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = var.single_nat_gateway ? aws_route_table.app[0].id : aws_route_table.app[count.index].id
}

# Data Isolated Route Table (No Internet route for absolute database isolation)
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-data-rt"
    Environment = var.environment
  })
}

resource "aws_route_table_association" "data" {
  count          = length(var.data_subnet_cidrs)
  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# =============================================================================
# 8. Tiered Security Groups
# =============================================================================

# ALB Security Group: Inbound HTTPS/HTTP from Internet, Outbound to App SG
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "Controls inbound web traffic to the LifeThread Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Allow inbound HTTPS from Internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Allow inbound HTTP from Internet (for redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound to VPC services"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-alb-sg"
    Environment = var.environment
  })
}

# Application Security Group: Inbound only from ALB, Outbound for APIs and Bedrock
resource "aws_security_group" "app" {
  name        = "${var.project_name}-${var.environment}-app-sg"
  description = "Controls ingress and egress for LifeThread ECS container tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow HTTP from ALB only"
    from_port       = var.app_port
    to_port         = var.app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Allow all outbound traffic for external API calls, S3, and Bedrock"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-app-sg"
    Environment = var.environment
  })
}

# Database Security Group: Inbound PostgreSQL from App SG ONLY
resource "aws_security_group" "database" {
  name        = "${var.project_name}-${var.environment}-db-sg"
  description = "Strict isolation for RDS PostgreSQL cluster; ingress only from app tier"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL access from ECS application tasks only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    description = "No outbound required for isolated DB"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-db-sg"
    Environment = var.environment
  })
}

# Redis Security Group: Inbound Redis from App SG ONLY
resource "aws_security_group" "redis" {
  name        = "${var.project_name}-${var.environment}-redis-sg"
  description = "Strict isolation for ElastiCache Redis; ingress only from app tier"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis access from ECS application tasks only"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    description = "Outbound to VPC only"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-redis-sg"
    Environment = var.environment
  })
}
