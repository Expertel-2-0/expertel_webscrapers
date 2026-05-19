# =============================================================================
# SCRAPER INSTANCE MODULE
# =============================================================================
# EC2 instance with XFCE desktop + noVNC for remote access
# Runs Playwright-based webscrapers with visible browser
# =============================================================================

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# IAM ROLE FOR EC2 INSTANCE
# -----------------------------------------------------------------------------

resource "aws_iam_role" "scraper" {
  name = "${var.app_name}-${var.environment}-scraper-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_instance_profile" "scraper" {
  name = "${var.app_name}-${var.environment}-scraper-profile"
  role = aws_iam_role.scraper.name
}

# SSM Managed Instance Core (for Session Manager access)
resource "aws_iam_role_policy_attachment" "ssm" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  role       = aws_iam_role.scraper.name
}

# CloudWatch Agent
resource "aws_iam_role_policy_attachment" "cloudwatch" {
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
  role       = aws_iam_role.scraper.name
}

# ECR Read Access
resource "aws_iam_role_policy" "ecr_access" {
  name = "${var.app_name}-${var.environment}-ecr-access"
  role = aws_iam_role.scraper.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

# SSM Parameter Store Read Access
resource "aws_iam_role_policy" "ssm_parameters" {
  name = "${var.app_name}-${var.environment}-ssm-parameters"
  role = aws_iam_role.scraper.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath"
        ]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.app_name}/${var.environment}/*"
        ]
      }
    ]
  })
}

# S3 Access for downloads/uploads (optional)
resource "aws_iam_role_policy" "s3_access" {
  count = var.s3_bucket_name != "" ? 1 : 0

  name = "${var.app_name}-${var.environment}-s3-access"
  role = aws_iam_role.scraper.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/*"
        ]
      }
    ]
  })
}

# SNS Publish for notifications
resource "aws_iam_role_policy" "sns_publish" {
  name = "${var.app_name}-${var.environment}-sns-publish"
  role = aws_iam_role.scraper.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = var.sns_topic_arn
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# SECURITY GROUP
# -----------------------------------------------------------------------------

resource "aws_security_group" "scraper" {
  name        = "${var.app_name}-${var.environment}-scraper-sg"
  description = "Security group for scraper instance with noVNC access"
  vpc_id      = var.vpc_id

  # SSH access (for debugging, optional)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
    description = "SSH access"
  }

  # HTTPS for noVNC (Nginx reverse proxy)
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.novnc_allowed_cidrs
    description = "HTTPS/noVNC access"
  }

  # HTTP for Let's Encrypt ACME challenge
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP for ACME challenge"
  }

  # Outbound - allow all
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = merge(var.tags, {
    Name = "${var.app_name}-${var.environment}-scraper-sg"
  })
}

# -----------------------------------------------------------------------------
# EC2 INSTANCE
# -----------------------------------------------------------------------------

resource "aws_instance" "scraper" {
  ami           = var.ami_id
  instance_type = var.instance_type
  subnet_id     = var.subnet_id
  key_name      = var.key_name

  vpc_security_group_ids = [
    aws_security_group.scraper.id,
    var.database_security_group_id
  ]

  iam_instance_profile = aws_iam_instance_profile.scraper.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    delete_on_termination = true
    encrypted             = true

    tags = merge(var.tags, {
      Name = "${var.app_name}-${var.environment}-scraper-root"
    })
  }

  user_data_base64 = base64gzip(templatefile("${path.module}/templates/user_data.sh", {
    environment            = var.environment
    app_name               = var.app_name
    aws_region             = var.aws_region
    github_repo_url        = var.github_repo_url
    github_branch          = var.github_branch
    sns_topic_arn          = var.sns_topic_arn
    screen_resolution      = var.screen_resolution
    timezone               = var.timezone
    scraper_timer_calendar = var.scraper_timer_calendar
  }))

  tags = merge(var.tags, {
    Name = "${var.app_name}-${var.environment}-scraper"
  })

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

# -----------------------------------------------------------------------------
# ELASTIC IP (optional, for consistent DNS)
# -----------------------------------------------------------------------------

resource "aws_eip" "scraper" {
  count    = var.create_elastic_ip ? 1 : 0
  instance = aws_instance.scraper.id
  domain   = "vpc"

  tags = merge(var.tags, {
    Name = "${var.app_name}-${var.environment}-scraper-eip"
  })
}

# -----------------------------------------------------------------------------
# CLOUDWATCH LOG GROUP
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "scraper" {
  name              = "/experteliq2/scraper/${var.environment}"
  retention_in_days = var.log_retention_days

  tags = var.tags
}
