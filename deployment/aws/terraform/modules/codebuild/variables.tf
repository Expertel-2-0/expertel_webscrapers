# =============================================================================
# CODEBUILD MODULE - VARIABLES
# =============================================================================

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "experteliq2-scraper"
}

variable "environment" {
  description = "Environment (dev, qa, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "github_repository_url" {
  description = "GitHub repository URL"
  type        = string
}

variable "source_branch" {
  description = "Branch to build from"
  type        = string
  default     = "main"
}

variable "buildspec_file" {
  description = "Path to buildspec file"
  type        = string
  default     = "buildspec.yml"
}

variable "compute_type" {
  description = "CodeBuild compute type"
  type        = string
  default     = "BUILD_GENERAL1_SMALL"
}

variable "instance_id" {
  description = "EC2 instance ID to deploy to"
  type        = string
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for notifications"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "enable_webhook" {
  description = "Enable GitHub webhook for automatic builds"
  type        = bool
  default     = false
}

variable "github_connection_name" {
  description = "Name of the CodeStar/CodeConnections GitHub connection used by CodeBuild to fetch source. Required for manual `aws codebuild start-build` calls — webhook-triggered builds work without it."
  type        = string
  default     = "experteliq2-codebuild"
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
