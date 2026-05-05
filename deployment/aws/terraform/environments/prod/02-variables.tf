# =============================================================================
# VARIABLES
# =============================================================================

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "experteliq2-scraper"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

# -----------------------------------------------------------------------------
# COMPUTE
# -----------------------------------------------------------------------------

variable "instance_type" {
  description = "EC2 instance type for scraper"
  type        = string
  default     = "t3.medium"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = "experteliq2-prod-key"
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 50
}

variable "screen_resolution" {
  description = "Virtual screen resolution"
  type        = string
  default     = "1920x1080"
}

# -----------------------------------------------------------------------------
# NETWORK ACCESS
# -----------------------------------------------------------------------------

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = []  # Empty = no SSH access from outside
}

variable "novnc_allowed_cidrs" {
  description = "CIDR blocks allowed for noVNC access"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # Allow from anywhere (protected by password)
}

# -----------------------------------------------------------------------------
# GITHUB
# -----------------------------------------------------------------------------

variable "github_repository_url" {
  description = "GitHub repository URL"
  type        = string
  default     = "https://github.com/Expertel-2-0/expertel_webscrapers.git"
}

variable "github_branch" {
  description = "GitHub branch for PROD environment"
  type        = string
  default     = "master"
}

variable "enable_webhook" {
  description = "Enable GitHub webhook for automatic builds"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# NOTIFICATIONS
# -----------------------------------------------------------------------------

variable "notification_emails" {
  description = "Email addresses for notifications"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# SCHEDULING
# -----------------------------------------------------------------------------

variable "timezone" {
  description = "Timezone for scheduled tasks"
  type        = string
  default     = "America/New_York"  # EST
}

# -----------------------------------------------------------------------------
# RETENTION
# -----------------------------------------------------------------------------

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}
