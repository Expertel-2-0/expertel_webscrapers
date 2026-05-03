#!/bin/bash
# =============================================================================
# ExpertelIQ2 Scraper - Plan PROD Environment
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/terraform/environments/prod"

echo "=========================================="
echo "ExpertelIQ2 Scraper - Plan PROD"
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

cd "$TERRAFORM_DIR"

echo "Initializing Terraform..."
terraform init

echo ""
echo "Planning changes..."
terraform plan

echo ""
echo "=========================================="
echo "Plan complete. Review changes above."
echo "To apply: ./deploy-prod.sh"
echo "=========================================="
