#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Setup ALL secrets for DEV environment

.DESCRIPTION
    Interactive setup of every required and optional secret in AWS SSM Parameter Store
    for DEV. Wrapper around Manage-Secrets.ps1 -Command setup.

.EXAMPLE
    .\Setup-Secrets-Dev.ps1
#>

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\Manage-Secrets.ps1" -Command setup -Environment dev
exit $LASTEXITCODE
