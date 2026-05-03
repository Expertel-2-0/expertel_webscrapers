#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Secrets Management Script for Windows

.DESCRIPTION
    Manages secrets in AWS Systems Manager Parameter Store.
    Secrets are stored as SecureString and never appear in Terraform state.

.PARAMETER Command
    Command to execute: setup, update, set, list, validate, get, delete

.PARAMETER Environment
    Target environment: dev, qa, prod, or custom

.PARAMETER SecretKey
    Secret key for 'set' and 'get' commands (e.g., database/password)

.PARAMETER Region
    AWS region (default: us-east-2)

.PARAMETER AppName
    Application name prefix (default: experteliq2-scraper)

.EXAMPLE
    .\Manage-Secrets.ps1 -Command setup -Environment dev

.EXAMPLE
    .\Manage-Secrets.ps1 -Command set -Environment qa -SecretKey database/password

.EXAMPLE
    .\Manage-Secrets.ps1 -Command list -Environment qa

.EXAMPLE
    .\Manage-Secrets.ps1 -Command get -Environment prod -SecretKey backend-api/key
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("setup", "update", "set", "list", "validate", "get", "delete", "help")]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Environment,

    [Parameter(Position = 2)]
    [string]$SecretKey,

    [Parameter()]
    [string]$Region = "us-east-2",

    [Parameter()]
    [string]$AppName = "experteliq2-scraper"
)

# =============================================================================
# SECRET REGISTRY (single source of truth)
# =============================================================================
# Type: S = SecureString, P = Plain (String)
# Required: R = Required, O = Optional

$SecretsRegistry = @(
    @{ Path = "database/password";    Type = "S"; Required = "R"; Description = "PostgreSQL password";     Prompt = "PostgreSQL Password" },
    @{ Path = "backend-api/key";      Type = "S"; Required = "R"; Description = "Backend API key";         Prompt = "Backend API Key" },
    @{ Path = "cryptography/key";     Type = "S"; Required = "R"; Description = "Cryptography key";        Prompt = "Cryptography Key" },
    @{ Path = "azure/client-id";      Type = "P"; Required = "R"; Description = "Azure AD client ID";      Prompt = "Azure Client ID" },
    @{ Path = "azure/tenant-id";      Type = "P"; Required = "R"; Description = "Azure AD tenant ID";      Prompt = "Azure Tenant ID" },
    @{ Path = "azure/client-secret";  Type = "S"; Required = "R"; Description = "Azure AD client secret";  Prompt = "Azure Client Secret" },
    @{ Path = "novnc/password";       Type = "S"; Required = "R"; Description = "noVNC access password";   Prompt = "noVNC Password" },
    @{ Path = "anthropic/api-key";    Type = "S"; Required = "O"; Description = "Anthropic API key";       Prompt = "Anthropic API Key" },
    @{ Path = "gemini/api-key";       Type = "S"; Required = "O"; Description = "Gemini API key";          Prompt = "Gemini API Key" },
    @{ Path = "two-captcha/api-key";  Type = "S"; Required = "O"; Description = "2Captcha API key";        Prompt = "2Captcha API Key" },
    @{ Path = "capsolver/api-key";    Type = "S"; Required = "O"; Description = "CapSolver API key";       Prompt = "CapSolver API Key" },
    @{ Path = "email/host-user";      Type = "P"; Required = "O"; Description = "SMTP host user";          Prompt = "Email SMTP Host User" },
    @{ Path = "email/host-password";  Type = "S"; Required = "O"; Description = "SMTP host password";      Prompt = "Email SMTP Host Password" },
    @{ Path = "slack/webhook-url";    Type = "S"; Required = "O"; Description = "Slack webhook URL";       Prompt = "Slack Webhook URL" },
    @{ Path = "teams/webhook-url";    Type = "S"; Required = "O"; Description = "Teams webhook URL";       Prompt = "Microsoft Teams Webhook URL" }
)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-ColorOutput {
    param([string]$Message, [string]$Color = "White")
    Write-Host $Message -ForegroundColor $Color
}

function Write-Success { param([string]$Message) Write-ColorOutput "[OK] $Message" "Green" }
function Write-Error { param([string]$Message) Write-ColorOutput "[ERROR] $Message" "Red" }
function Write-Warning { param([string]$Message) Write-ColorOutput "[WARN] $Message" "Yellow" }
function Write-Info { param([string]$Message) Write-ColorOutput "[INFO] $Message" "Cyan" }

function Show-Help {
    Write-Info "ExpertelIQ2 Scraper - AWS Secrets Management"
    Write-Host ""
    Write-Host "Usage: .\Manage-Secrets.ps1 -Command <command> -Environment <env> [options]"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  setup <env>     - Initial setup of ALL secrets for environment"
    Write-Host "  update <env>    - Update ALL existing secrets for environment"
    Write-Host "  set <env> <key> - Set a single specific secret (interactive prompt)"
    Write-Host "  list <env>      - List all secrets for environment"
    Write-Host "  validate <env>  - Validate required secrets exist"
    Write-Host "  get <env> <key> - Get specific secret value"
    Write-Host "  delete <env>    - Delete all secrets for environment (DANGEROUS!)"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Region <region>    AWS region (default: us-east-2)"
    Write-Host "  -AppName <name>     Application name (default: experteliq2-scraper)"
    Write-Host ""
    Write-Host "Environments:"
    Write-Host "  dev, qa, prod (or any custom name)"
    Write-Host ""
    Write-Host "SSM Parameters Created:"
    Write-Host "  REQUIRED:"
    foreach ($e in ($SecretsRegistry | Where-Object { $_.Required -eq "R" })) {
        Write-Host ("    /{app}/{env}/{0,-25} - {1}" -f $e.Path, $e.Description)
    }
    Write-Host ""
    Write-Host "  OPTIONAL:"
    foreach ($e in ($SecretsRegistry | Where-Object { $_.Required -eq "O" })) {
        Write-Host ("    /{app}/{env}/{0,-25} - {1}" -f $e.Path, $e.Description)
    }
    Write-Host ""
    Write-Host "Valid secret keys:"
    Write-Host ("  " + (($SecretsRegistry | ForEach-Object { $_.Path }) -join ", "))
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\Manage-Secrets.ps1 -Command setup -Environment dev"
    Write-Host "  .\Manage-Secrets.ps1 -Command set -Environment dev -SecretKey database/password"
    Write-Host "  .\Manage-Secrets.ps1 -Command set -Environment qa -SecretKey email/host-password"
    Write-Host "  .\Manage-Secrets.ps1 -Command list -Environment qa"
    Write-Host "  .\Manage-Secrets.ps1 -Command get -Environment prod -SecretKey backend-api/key"
}

# =============================================================================
# AWS CLI CHECKS
# =============================================================================

function Test-AwsCli {
    try {
        $null = Get-Command aws -ErrorAction Stop
        return $true
    }
    catch {
        Write-Error "AWS CLI is not installed"
        Write-Host "Install from: https://aws.amazon.com/cli/"
        return $false
    }
}

function Test-AwsCredentials {
    try {
        $result = aws sts get-caller-identity --region $Region 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "AWS credentials not configured"
        }
        return $true
    }
    catch {
        Write-Error "AWS credentials not configured or invalid"
        Write-Host "Run: aws configure"
        return $false
    }
}

# =============================================================================
# SSM PARAMETER FUNCTIONS
# =============================================================================

function Read-Secret {
    param(
        [string]$Prompt,
        [bool]$IsSensitive = $true
    )

    if ($IsSensitive) {
        $secureString = Read-Host -Prompt $Prompt -AsSecureString
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureString)
        return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    }
    else {
        return Read-Host -Prompt $Prompt
    }
}

function Set-SsmParameter {
    param(
        [string]$Name,
        [string]$Value,
        [string]$Type = "SecureString",
        [string]$Description
    )

    Write-Info "Storing parameter: $Name"

    try {
        $result = aws ssm put-parameter `
            --region $Region `
            --name $Name `
            --value $Value `
            --type $Type `
            --description $Description `
            --overwrite 2>&1

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Successfully stored: $Name"
            return $true
        }
        else {
            Write-Error "Failed to store: $Name"
            Write-Host $result
            return $false
        }
    }
    catch {
        Write-Error "Failed to store: $Name - $_"
        return $false
    }
}

function Get-SsmParameter {
    param(
        [string]$Name,
        [bool]$WithDecryption = $true
    )

    $decryptFlag = if ($WithDecryption) { "--with-decryption" } else { "" }

    try {
        $value = aws ssm get-parameter `
            --region $Region `
            --name $Name `
            $decryptFlag `
            --query 'Parameter.Value' `
            --output text 2>&1

        if ($LASTEXITCODE -eq 0) {
            return $value
        }
        return $null
    }
    catch {
        return $null
    }
}

function Get-SsmParameters {
    $path = "/$AppName/$Environment"

    Write-Info "Parameters for ${AppName}/${Environment}:"
    Write-Host "================================================"

    aws ssm get-parameters-by-path `
        --region $Region `
        --path $path `
        --recursive `
        --query 'Parameters[*].[Name,Type,LastModifiedDate]' `
        --output table
}

function Remove-SsmParameters {
    $path = "/$AppName/$Environment"

    Write-Error "WARNING: This will delete ALL parameters for $AppName/$Environment"
    Write-Error "This action cannot be undone!"
    Write-Host ""

    $confirmation = Read-Host "Type 'DELETE' to confirm"

    if ($confirmation -ne "DELETE") {
        Write-Host "Deletion cancelled."
        return
    }

    $parameters = aws ssm get-parameters-by-path `
        --region $Region `
        --path $path `
        --recursive `
        --query 'Parameters[*].Name' `
        --output text 2>&1

    if ([string]::IsNullOrWhiteSpace($parameters)) {
        Write-Host "No parameters found to delete."
        return
    }

    foreach ($param in $parameters.Split("`t")) {
        if (![string]::IsNullOrWhiteSpace($param)) {
            Write-Warning "Deleting: $param"
            aws ssm delete-parameter --region $Region --name $param 2>&1 | Out-Null
        }
    }

    Write-Success "Deletion completed"
}

# Prompt and store a single secret from registry entry
function Set-SecretFromEntry {
    param([hashtable]$Entry)

    $prefix = "/$AppName/$Environment"
    $isSensitive = $Entry.Type -eq "S"
    $ssmType = if ($isSensitive) { "SecureString" } else { "String" }
    $label = if ($Entry.Required -eq "R") { "(REQUIRED)" } else { "(optional)" }

    $value = Read-Secret -Prompt "$($Entry.Prompt) $label" -IsSensitive $isSensitive

    if (![string]::IsNullOrWhiteSpace($value)) {
        Set-SsmParameter -Name "$prefix/$($Entry.Path)" -Value $value -Type $ssmType -Description $Entry.Description
    }
    elseif ($Entry.Required -eq "R") {
        Write-Error "Error: $($Entry.Path) is required"
        exit 1
    }
    else {
        Write-Warning "Skipped: $($Entry.Path)"
    }
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if ($Command -eq "help") {
    Show-Help
    exit 0
}

# Validate environment
if ([string]::IsNullOrWhiteSpace($Environment)) {
    Write-Error "Error: Environment is required"
    Show-Help
    exit 1
}

# Warn for non-standard environments
$standardEnvs = @("dev", "qa", "prod")
if ($Environment -notin $standardEnvs) {
    Write-Warning "Warning: Using non-standard environment name: $Environment"
    $confirm = Read-Host "Continue? (y/N)"
    if ($confirm -notmatch "^[Yy]$") {
        exit 0
    }
}

# Check prerequisites
if (-not (Test-AwsCli)) { exit 1 }
if (-not (Test-AwsCredentials)) { exit 1 }

# Execute command
switch ($Command) {
    { $_ -in "setup", "update" } {
        Write-Info "=========================================================="
        Write-Info "  Setting up secrets for $AppName/$Environment"
        Write-Info "=========================================================="
        Write-Host ""
        Write-Warning "All values will be stored in AWS SSM Parameter Store"
        Write-Warning "Press Enter to skip optional parameters"
        Write-Host ""

        # Required secrets
        Write-Success "--- REQUIRED SECRETS ---"
        Write-Host ""
        foreach ($entry in ($SecretsRegistry | Where-Object { $_.Required -eq "R" })) {
            Set-SecretFromEntry -Entry $entry
        }

        Write-Host ""
        # Optional secrets
        Write-Success "--- OPTIONAL SECRETS (press Enter to skip) ---"
        Write-Host ""
        foreach ($entry in ($SecretsRegistry | Where-Object { $_.Required -eq "O" })) {
            Set-SecretFromEntry -Entry $entry
        }

        Write-Host ""
        Write-Success "=========================================================="
        Write-Success "Secrets setup completed for $Environment environment"
        Write-Success "=========================================================="
        Write-Host ""
        Write-Info "To verify, run: .\Manage-Secrets.ps1 -Command list -Environment $Environment"
    }
    "set" {
        if ([string]::IsNullOrWhiteSpace($SecretKey)) {
            Write-Error "Error: SecretKey is required for set command"
            Write-Host "Usage: .\Manage-Secrets.ps1 -Command set -Environment <env> -SecretKey <key>"
            Write-Host "Example: .\Manage-Secrets.ps1 -Command set -Environment dev -SecretKey database/password"
            Write-Host ""
            Write-Host "Valid keys:"
            foreach ($e in $SecretsRegistry) {
                Write-Host ("  {0,-25} - {1}" -f $e.Path, $e.Description)
            }
            exit 1
        }

        # Validate the secret key against registry
        $entry = $SecretsRegistry | Where-Object { $_.Path -eq $SecretKey }
        if (-not $entry) {
            Write-Error "Error: Unknown secret key: $SecretKey"
            Write-Host ""
            Write-Host "Valid keys:"
            foreach ($e in $SecretsRegistry) {
                Write-Host ("  {0,-25} - {1}" -f $e.Path, $e.Description)
            }
            exit 1
        }

        $isSensitive = $entry.Type -eq "S"
        $ssmType = if ($isSensitive) { "SecureString" } else { "String" }

        $paramName = "/$AppName/$Environment/$SecretKey"
        Write-Info "Setting secret: $paramName"

        $secretValue = Read-Secret -Prompt "Enter value for $SecretKey" -IsSensitive $isSensitive
        if ([string]::IsNullOrWhiteSpace($secretValue)) {
            Write-Error "Error: Value cannot be empty"
            exit 1
        }

        Set-SsmParameter -Name $paramName -Value $secretValue -Type $ssmType -Description $entry.Description
        Write-Host ""
        Write-Success "Secret $SecretKey updated for $Environment environment"
    }
    "list" {
        Get-SsmParameters
    }
    "validate" {
        Write-Info "Validating secrets for $Environment environment"

        $prefix = "/$AppName/$Environment"
        $allValid = $true

        Write-Host ""
        Write-Host "Required secrets:"
        foreach ($entry in ($SecretsRegistry | Where-Object { $_.Required -eq "R" })) {
            $value = Get-SsmParameter -Name "$prefix/$($entry.Path)"
            if ($value) {
                Write-Success $entry.Path
            }
            else {
                Write-Error "$($entry.Path) (MISSING)"
                $allValid = $false
            }
        }

        Write-Host ""
        Write-Host "Optional secrets:"
        foreach ($entry in ($SecretsRegistry | Where-Object { $_.Required -eq "O" })) {
            $value = Get-SsmParameter -Name "$prefix/$($entry.Path)"
            if ($value) {
                Write-Success $entry.Path
            }
            else {
                Write-Warning "$($entry.Path) (not set)"
            }
        }

        Write-Host ""
        if ($allValid) {
            Write-Success "All required secrets are configured"
        }
        else {
            Write-Error "Some required secrets are missing"
            exit 1
        }
    }
    "get" {
        if ([string]::IsNullOrWhiteSpace($SecretKey)) {
            Write-Error "Error: SecretKey is required for get command"
            Write-Host "Usage: .\Manage-Secrets.ps1 -Command get -Environment <env> -SecretKey <key>"
            Write-Host "Example: .\Manage-Secrets.ps1 -Command get -Environment dev -SecretKey database/password"
            exit 1
        }

        $paramName = "/$AppName/$Environment/$SecretKey"
        $value = Get-SsmParameter -Name $paramName

        if ($value) {
            Write-Success "Parameter: $paramName"
            Write-Host "Value: $value"
        }
        else {
            Write-Error "Parameter not found: $paramName"
            exit 1
        }
    }
    "delete" {
        Remove-SsmParameters
    }
    default {
        Write-Error "Unknown command: $Command"
        Show-Help
        exit 1
    }
}