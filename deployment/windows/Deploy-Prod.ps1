#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Deploy PROD Environment

.DESCRIPTION
    Wrapper around Deploy-Environment.ps1 for PROD. Mirrors deployment/aws/deploy-prod.sh.
    WARNING: This deploys to PRODUCTION. Always require explicit confirmation.

.EXAMPLE
    .\Deploy-Prod.ps1
#>

[CmdletBinding()]
param()

# Colors
function Write-Warning2 { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Info     { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }

Write-Info "=========================================="
Write-Info "ExpertelIQ2 Scraper - Deploy PROD"
Write-Info "=========================================="
Write-Warning2 "WARNING: This is PRODUCTION environment!"
Write-Info "=========================================="

# Production deploys never auto-approve. The wrapper drops -AutoApprove on purpose
# so the underlying Deploy-Environment.ps1 always asks for explicit 'yes'.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Deploy-Environment.ps1" -Environment prod
exit $LASTEXITCODE
