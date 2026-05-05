# =============================================================================
# CODEBUILD MODULE FOR SCRAPER CI/CD
# =============================================================================
# GitHub push → CodeBuild → SSM Command → EC2 Git Pull & Restart
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
# IAM ROLE FOR CODEBUILD
# -----------------------------------------------------------------------------

resource "aws_iam_role" "codebuild" {
  name = "${var.app_name}-${var.environment}-codebuild-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "codebuild.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# Lookup the GitHub connection so we can grant UseConnection to the role.
# Webhook-triggered builds use the connection implicitly via the webhook
# resource; manual `aws codebuild start-build` calls fail with
# "Access denied to connection" unless the role itself has this permission.
data "aws_codestarconnections_connection" "github" {
  name = var.github_connection_name
}

resource "aws_iam_role_policy" "codebuild" {
  name = "${var.app_name}-${var.environment}-codebuild-policy"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/codebuild/${var.app_name}-${var.environment}",
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/codebuild/${var.app_name}-${var.environment}:*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = var.sns_topic_arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.codebuild_cache.arn}",
          "${aws_s3_bucket.codebuild_cache.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "codeconnections:UseConnection",
          "codeconnections:GetConnection",
          "codeconnections:GetConnectionToken",
          "codestar-connections:UseConnection",
          "codestar-connections:GetConnection",
          "codestar-connections:GetConnectionToken"
        ]
        Resource = data.aws_codestarconnections_connection.github.arn
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# S3 BUCKET FOR CODEBUILD CACHE
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "codebuild_cache" {
  bucket = "${var.app_name}-${var.environment}-codebuild-cache"

  tags = merge(var.tags, {
    Name = "${var.app_name}-${var.environment}-codebuild-cache"
  })
}

resource "aws_s3_bucket_versioning" "codebuild_cache" {
  bucket = aws_s3_bucket.codebuild_cache.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "codebuild_cache" {
  bucket = aws_s3_bucket.codebuild_cache.id

  rule {
    id     = "delete-old-cache"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 7
    }
  }
}

# -----------------------------------------------------------------------------
# CLOUDWATCH LOG GROUP
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${var.app_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

# -----------------------------------------------------------------------------
# CODEBUILD PROJECT
# -----------------------------------------------------------------------------

resource "aws_codebuild_project" "scraper" {
  name          = "${var.app_name}-${var.environment}"
  description   = "Build and deploy scraper for ${var.environment}"
  build_timeout = "30"
  service_role  = aws_iam_role.codebuild.arn

  artifacts {
    type = "NO_ARTIFACTS"
  }

  cache {
    type     = "S3"
    location = aws_s3_bucket.codebuild_cache.bucket
  }

  environment {
    compute_type                = var.compute_type
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }

    environment_variable {
      name  = "ENVIRONMENT"
      value = var.environment
    }

    environment_variable {
      name  = "INSTANCE_ID"
      value = var.instance_id
    }

    environment_variable {
      name  = "SNS_TOPIC_ARN"
      value = var.sns_topic_arn
    }

    environment_variable {
      name  = "APP_DIR"
      value = "/opt/${var.app_name}"
    }

    environment_variable {
      name  = "GITHUB_BRANCH"
      value = var.source_branch
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild.name
    }
  }

  source {
    type            = "GITHUB"
    location        = var.github_repository_url
    git_clone_depth = 1
    buildspec       = var.buildspec_file

    git_submodules_config {
      fetch_submodules = false
    }
  }

  source_version = var.source_branch

  tags = merge(var.tags, {
    Name = "${var.app_name}-${var.environment}-codebuild"
  })
}

# -----------------------------------------------------------------------------
# GITHUB WEBHOOK
# -----------------------------------------------------------------------------

resource "aws_codebuild_webhook" "github" {
  count        = var.enable_webhook ? 1 : 0
  project_name = aws_codebuild_project.scraper.name
  build_type   = "BUILD"

  filter_group {
    filter {
      type    = "EVENT"
      pattern = "PUSH"
    }
    filter {
      type    = "HEAD_REF"
      pattern = "^refs/heads/${var.source_branch}$"
    }
  }
}
