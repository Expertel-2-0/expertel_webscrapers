#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Plan PROD Environment

.DESCRIPTION
    Wrapper around Plan-Environment.ps1 for PROD. Mirrors deployment/aws/plan-prod.sh.

.EXAMPLE
    .\Plan-Prod.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Plan-Environment.ps1" -Environment prod
exit $LASTEXITCODE
