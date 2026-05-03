#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Plan Script for Windows

.PARAMETER Environment
    Target environment: dev, qa, prod

.EXAMPLE
    .\Plan-Environment.ps1 -Environment qa

.EXAMPLE
    .\Plan-Environment.ps1 -Environment prod
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("dev", "qa", "prod")]
    [string]$Environment
)

# Colors
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Error { param([string]$Message) Write-Host $Message -ForegroundColor Red }
function Write-Warning { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }

Write-Info "=========================================="
Write-Info "ExpertelIQ2 Scraper - Plan"
Write-Info "Environment: $Environment"
Write-Info "=========================================="

if ($Environment -eq "prod") {
    Write-Warning "WARNING: This is PRODUCTION environment!"
}

# Check Terraform
try {
    $null = Get-Command terraform -ErrorAction Stop
}
catch {
    Write-Error "Error: Terraform is not installed"
    exit 1
}

# Check AWS CLI
try {
    $null = Get-Command aws -ErrorAction Stop
    $null = aws sts get-caller-identity 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Error: AWS credentials not configured"
        exit 1
    }
}
catch {
    Write-Error "Error: AWS CLI is not installed"
    exit 1
}

# Get Terraform directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TerraformDir = Join-Path (Split-Path -Parent $ScriptDir) "aws\terraform\environments\$Environment"

if (-not (Test-Path $TerraformDir)) {
    Write-Error "Terraform directory not found: $TerraformDir"
    exit 1
}

Push-Location $TerraformDir

try {
    # Initialize
    Write-Info "Initializing Terraform..."
    terraform init
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Terraform initialization failed"
        exit 1
    }

    # Plan
    Write-Host ""
    Write-Info "Planning changes..."
    terraform plan
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Terraform plan failed"
        exit 1
    }

    Write-Host ""
    Write-Success "=========================================="
    Write-Success "Plan complete. Review changes above."
    Write-Success "To apply: .\Deploy-Environment.ps1 -Environment $Environment"
    Write-Success "=========================================="
}
finally {
    Pop-Location
}
