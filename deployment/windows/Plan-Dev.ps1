#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Plan DEV Environment

.DESCRIPTION
    Wrapper around Plan-Environment.ps1 for DEV. Mirrors deployment/aws/plan-dev.sh.

.EXAMPLE
    .\Plan-Dev.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Plan-Environment.ps1" -Environment dev
exit $LASTEXITCODE
