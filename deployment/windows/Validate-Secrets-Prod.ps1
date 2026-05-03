#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Validate secrets for PROD environment

.DESCRIPTION
    Verifies all required SSM parameters exist for PROD. Wrapper around
    Manage-Secrets.ps1 -Command validate. Returns non-zero exit code if any
    required secret is missing.

.EXAMPLE
    .\Validate-Secrets-Prod.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Manage-Secrets.ps1" -Command validate -Environment prod
exit $LASTEXITCODE
