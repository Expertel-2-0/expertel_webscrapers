#!/bin/bash
# =============================================================================
# ExpertelIQ2 Scraper - Deploy PROD Environment
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/terraform/environments/prod"

echo "=========================================="
echo "ExpertelIQ2 Scraper - Deploy PROD"
echo "=========================================="
echo "WARNING: This is PRODUCTION environment!"
echo "=========================================="

# Check Terraform
if ! command -v terraform &> /dev/null; then
    echo "Error: Terraform is not installed"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo "Error: AWS credentials not configured"
    exit 1
fi

# Validate secrets first
echo "Validating secrets..."
"$SCRIPT_DIR/manage-secrets.sh" validate prod || {
    echo ""
    echo "Error: Required secrets are missing."
    echo "Run: ./manage-secrets.sh setup prod"
    exit 1
}

cd "$TERRAFORM_DIR"

echo ""
echo "Initializing Terraform..."
terraform init

echo ""
echo "Planning changes..."
terraform plan -out=tfplan

echo ""
echo "PRODUCTION DEPLOYMENT - Please review carefully!"
read -p "Type 'yes' to confirm PRODUCTION deployment: " confirm
if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled."
    rm -f tfplan
    exit 0
fi

echo ""
echo "Applying changes..."
terraform apply tfplan
rm -f tfplan

echo ""
echo "=========================================="
echo "PRODUCTION Deployment Complete!"
echo "=========================================="

# Show outputs
echo ""
echo "Instance Information:"
terraform output instance_public_ip
terraform output novnc_url
terraform output ssh_command

echo ""
echo "Next Steps:"
echo "1. Wait 5-10 minutes for instance to fully initialize"
echo "2. Access noVNC at the URL above"
echo "3. Check scraper timer: ssh to instance, run 'systemctl status scraper.timer'"
echo "=========================================="
