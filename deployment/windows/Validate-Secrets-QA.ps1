#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Validate secrets for QA environment

.DESCRIPTION
    Verifies all required SSM parameters exist for QA. Wrapper around
    Manage-Secrets.ps1 -Command validate. Returns non-zero exit code if any
    required secret is missing.

.EXAMPLE
    .\Validate-Secrets-QA.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Manage-Secrets.ps1" -Command validate -Environment qa
exit $LASTEXITCODE
