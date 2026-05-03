#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Deploy DEV Environment

.DESCRIPTION
    Wrapper around Deploy-Environment.ps1 for DEV. Mirrors deployment/aws/deploy-dev.sh.

.PARAMETER AutoApprove
    Skip confirmation prompts

.EXAMPLE
    .\Deploy-Dev.ps1

.EXAMPLE
    .\Deploy-Dev.ps1 -AutoApprove
#>

[CmdletBinding()]
param(
    [Parameter()]
    [switch]$AutoApprove
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($AutoApprove) {
    & "$ScriptDir\Deploy-Environment.ps1" -Environment dev -AutoApprove
} else {
    & "$ScriptDir\Deploy-Environment.ps1" -Environment dev
}
exit $LASTEXITCODE
