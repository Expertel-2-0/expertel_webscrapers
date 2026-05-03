#Requires -Version 5.1
<#
.SYNOPSIS
    ExpertelIQ2 Scraper - Terraform Deploy QA Environment

.DESCRIPTION
    Wrapper around Deploy-Environment.ps1 for QA. Mirrors deployment/aws/deploy-qa.sh.

.PARAMETER AutoApprove
    Skip confirmation prompts

.EXAMPLE
    .\Deploy-QA.ps1

.EXAMPLE
    .\Deploy-QA.ps1 -AutoApprove
#>

[CmdletBinding()]
param(
    [Parameter()]
    [switch]$AutoApprove
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($AutoApprove) {
    & "$ScriptDir\Deploy-Environment.ps1" -Environment qa -AutoApprove
} else {
    & "$ScriptDir\Deploy-Environment.ps1" -Environment qa
}
exit $LASTEXITCODE
