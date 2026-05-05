# =============================================================================
# COMPUTE - SCRAPER INSTANCE
# =============================================================================

module "scraper_instance" {
  source = "../../modules/scraper-instance"

  app_name       = var.app_name
  environment    = var.environment
  aws_region     = var.aws_region
  aws_account_id = data.aws_caller_identity.current.account_id

  # Network
  vpc_id    = data.aws_vpc.backend.id
  subnet_id = data.aws_subnets.public.ids[0]

  # Instance
  ami_id           = data.aws_ami.ubuntu.id
  instance_type    = var.instance_type
  key_name         = var.key_name
  root_volume_size = var.root_volume_size

  # Security
  database_security_group_id = data.aws_security_group.backend_app.id
  ssh_allowed_cidrs          = var.ssh_allowed_cidrs
  novnc_allowed_cidrs        = var.novnc_allowed_cidrs

  # Application
  github_repo_url   = var.github_repository_url
  github_branch     = var.github_branch
  sns_topic_arn     = module.notifications.sns_topic_arn
  screen_resolution = var.screen_resolution
  timezone          = var.timezone

  # Logs
  log_retention_days = var.log_retention_days
  # No Elastic IP: nadie externo se conecta a esta instancia. Si en el futuro
  # alguien necesita IP estable (ej. allowlist en un portal), cambiar a true
  # y validar quota EC2-VPC Elastic IPs en us-east-2 (default 5).
  create_elastic_ip  = false

  tags = local.common_tags

  depends_on = [module.notifications]
}
