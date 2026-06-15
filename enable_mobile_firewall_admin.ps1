$ErrorActionPreference = "Stop"

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $IsAdmin) {
    throw "Run this script from PowerShell as Administrator."
}

try {
    Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
    Write-Host "Wi-Fi network profile changed to Private."
} catch {
    Write-Host "Could not change Wi-Fi network profile: $($_.Exception.Message)"
}

$RuleName = "Money Management Streamlit 8501-8510"
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8501-8510 `
    -Profile Private,Public | Out-Null

Write-Host "Firewall rule created: $RuleName"
Write-Host "Phone URL should be available while run_mobile.ps1 or Streamlit is running."
