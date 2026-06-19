# =============================================================================
# SSM PARAMETERS (Non-secret configuration)
# =============================================================================
# These parameters are auto-generated from Terraform outputs
# Secrets are managed separately via manage-secrets.sh
# =============================================================================

# -----------------------------------------------------------------------------
# DATABASE CONFIGURATION (from backend app-settings JSON)
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "db_host" {
  name        = "/${var.app_name}/${var.environment}/database/host"
  description = "PostgreSQL host (from backend app-settings)"
  type        = "String"
  value       = local.db_host

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_name" {
  name        = "/${var.app_name}/${var.environment}/database/name"
  description = "PostgreSQL database name (from backend app-settings)"
  type        = "String"
  value       = local.db_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_port" {
  name        = "/${var.app_name}/${var.environment}/database/port"
  description = "PostgreSQL port (from backend app-settings)"
  type        = "String"
  value       = local.db_port

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_username" {
  name        = "/${var.app_name}/${var.environment}/database/username"
  description = "PostgreSQL username (from backend app-settings)"
  type        = "String"
  value       = local.db_user

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# BACKEND API CONFIGURATION
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "backend_url" {
  name        = "/${var.app_name}/${var.environment}/backend-api/url"
  description = "Backend API URL (from backend alb-url, already includes http://)"
  type        = "String"
  value       = data.aws_ssm_parameter.backend_url.value

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# AZURE CONFIGURATION (non-secret parts)
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "azure_user_email" {
  name        = "/${var.app_name}/${var.environment}/azure/user-email"
  description = "Azure user email for notifications"
  type        = "String"
  value       = "notifications@expertel.com"

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# MFA SERVICE
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "mfa_service_url" {
  name        = "/${var.app_name}/${var.environment}/mfa-service/url"
  description = "MFA service URL"
  type        = "String"
  value       = "http://localhost:7000"  # Update with actual MFA service URL

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# EMAIL CONFIGURATION (non-secret parts)
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "email_host" {
  name        = "/${var.app_name}/${var.environment}/email/host"
  description = "SMTP host"
  type        = "String"
  value       = "smtp.office365.com"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "email_port" {
  name        = "/${var.app_name}/${var.environment}/email/port"
  description = "SMTP port"
  type        = "String"
  value       = "587"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "email_use_tls" {
  name        = "/${var.app_name}/${var.environment}/email/use-tls"
  description = "Use TLS for SMTP"
  type        = "String"
  value       = "True"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "email_from_address" {
  name        = "/${var.app_name}/${var.environment}/email/from-address"
  description = "Email sender address"
  type        = "String"
  value       = "iqnotifications@expertel.com"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "scraper_alert_emails" {
  name        = "/${var.app_name}/${var.environment}/email/alert-recipients"
  description = "Comma-separated list of scraper alert email recipients"
  type        = "String"
  value       = "nelson@expertel.com"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "scraper_execution_log_emails" {
  name        = "/${var.app_name}/${var.environment}/email/execution-log-recipients"
  description = "Comma-separated recipients for scraper execution log summaries"
  type        = "String"
  value       = "alejandro@expertel.com"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "scraper_per_job_alerts_enabled" {
  name        = "/${var.app_name}/${var.environment}/email/per-job-alerts-enabled"
  description = "Toggle per-job scraper failure alert emails (the daily digest covers these; default off)"
  type        = "String"
  value       = "False"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "frontend_url" {
  name        = "/${var.app_name}/${var.environment}/config/frontend-url"
  description = "Frontend URL for building links in emails"
  type        = "String"
  value       = "http://experteliq2-frontend-qa-alb-2046627328.us-east-2.elb.amazonaws.com"

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# INSTANCE INFO
# -----------------------------------------------------------------------------

resource "aws_ssm_parameter" "instance_id" {
  name        = "/${var.app_name}/${var.environment}/instance/id"
  description = "Scraper EC2 instance ID"
  type        = "String"
  value       = module.scraper_instance.instance_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "novnc_url" {
  name        = "/${var.app_name}/${var.environment}/config/novnc-url"
  description = "noVNC access URL"
  type        = "String"
  value       = "https://${module.scraper_instance.instance_public_ip}/vnc/"

  tags = local.common_tags
}
