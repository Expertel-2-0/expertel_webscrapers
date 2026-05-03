#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Plan QA Environment

.DESCRIPTION
    Wrapper around Plan-Environment.ps1 for QA. Mirrors deployment/aws/plan-qa.sh.

.EXAMPLE
    .\Plan-QA.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Plan-Environment.ps1" -Environment qa
exit $LASTEXITCODE
