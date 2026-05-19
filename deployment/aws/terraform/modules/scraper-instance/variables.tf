# =============================================================================
# SCRAPER INSTANCE MODULE - VARIABLES
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

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the instance will be created"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for the instance (should be public for noVNC access)"
  type        = string
}

variable "ami_id" {
  description = "AMI ID for Ubuntu 22.04"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.medium"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 50
}

variable "database_security_group_id" {
  description = "Security group ID of the database instance (for DB access)"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = []
}

variable "novnc_allowed_cidrs" {
  description = "CIDR blocks allowed for noVNC access (0.0.0.0/0 for anywhere)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "github_repo_url" {
  description = "GitHub repository URL"
  type        = string
}

variable "github_branch" {
  description = "GitHub branch to clone"
  type        = string
  default     = "main"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for file storage (optional)"
  type        = string
  default     = ""
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for notifications"
  type        = string
}

variable "screen_resolution" {
  description = "Virtual screen resolution for noVNC"
  type        = string
  default     = "1920x1080"
}

variable "timezone" {
  description = "Timezone for scheduled tasks"
  type        = string
  default     = "America/New_York"
}

variable "scraper_timer_calendar" {
  description = "systemd OnCalendar expression for the scraper timer (e.g. '*:0/10' for every 10 min, '*:00,30' for every 30 min)"
  type        = string
  default     = "*:0/10"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "create_elastic_ip" {
  description = "Whether to create an Elastic IP for the instance"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
