# =============================================================================
# DATA SOURCES
# =============================================================================
# Reference existing resources from the backend infrastructure

# -----------------------------------------------------------------------------
# VPC AND NETWORKING (from backend)
# -----------------------------------------------------------------------------

# Get the VPC created by the backend
data "aws_vpc" "backend" {
  filter {
    name   = "tag:Name"
    values = ["${local.backend_app_name}-${var.environment}-vpc"]
  }
}

# Get public subnets from the backend VPC (by name pattern)
data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.backend.id]
  }

  filter {
    name   = "tag:Name"
    values = ["${local.backend_app_name}-${var.environment}-public-subnet-*"]
  }
}

# -----------------------------------------------------------------------------
# SECURITY GROUPS (from backend)
# -----------------------------------------------------------------------------

# Get the app security group from backend
data "aws_security_group" "backend_app" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.backend.id]
  }

  filter {
    name   = "tag:Name"
    values = ["${local.backend_app_name}-${var.environment}-app-sg"]
  }
}

# -----------------------------------------------------------------------------
# SSM PARAMETERS (from backend)
# -----------------------------------------------------------------------------

# Get app-settings JSON from backend (contains db_host, db_port, db_name, etc.)
data "aws_ssm_parameter" "backend_app_settings" {
  name = "/${local.backend_app_name}/${var.environment}/config/app-settings"
}

# Get backend ALB URL
data "aws_ssm_parameter" "backend_url" {
  name = "/${local.backend_app_name}/${var.environment}/config/alb-url"
}

# -----------------------------------------------------------------------------
# PARSED BACKEND CONFIGURATION
# -----------------------------------------------------------------------------
# Parse the JSON from backend app-settings to extract database configuration

locals {
  backend_config = jsondecode(data.aws_ssm_parameter.backend_app_settings.value)

  # Database configuration from backend (always defined in JSON)
  db_host = local.backend_config.db_host
  db_port = local.backend_config.db_port
  db_name = local.backend_config.db_name
  db_user = local.backend_config.db_user
}

# -----------------------------------------------------------------------------
# AMI
# -----------------------------------------------------------------------------

# Get latest Ubuntu 22.04 AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]  # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
