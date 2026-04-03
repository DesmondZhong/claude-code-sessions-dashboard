# Install claude-sessions agent as a Windows service using NSSM or as a scheduled task
# Run as Administrator

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$agentPy = Join-Path $scriptDir "agent.py"
$config = Join-Path $scriptDir "agent-config.yaml"
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

if (-not (Test-Path $agentPy)) {
    Write-Error "agent.py not found at $agentPy"
    exit 1
}

if (-not (Test-Path $config)) {
    Write-Error "agent-config.yaml not found. Copy and edit it first."
    exit 1
}

$nssm = Get-Command nssm -ErrorAction SilentlyContinue

if ($nssm) {
    Write-Host "Installing Windows service via NSSM..."
    nssm install claude-dashboard-agent $python "$agentPy --daemon --config $config"
    nssm set claude-dashboard-agent AppDirectory $scriptDir
    nssm set claude-dashboard-agent Description "Claude Sessions Dashboard Agent"
    nssm set claude-dashboard-agent Start SERVICE_AUTO_START
    nssm start claude-dashboard-agent
    Write-Host "Done! Agent service installed and started."
    Write-Host "  nssm status claude-dashboard-agent"
    Write-Host "  nssm stop claude-dashboard-agent"
    Write-Host "  nssm restart claude-dashboard-agent"
    Write-Host "  nssm remove claude-dashboard-agent confirm   (to uninstall)"
} else {
    Write-Host "NSSM not found. Installing as a scheduled task (runs at logon)..."
    $action = New-ScheduledTaskAction -Execute $python -Argument "$agentPy --daemon --config $config" -WorkingDirectory $scriptDir
    $trigger = New-ScheduledTaskTrigger -AtLogon
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
    Register-ScheduledTask -TaskName "ClaudeDashboardAgent" -Action $action -Trigger $trigger -Settings $settings -Description "Claude Sessions Dashboard Agent"
    Start-ScheduledTask -TaskName "ClaudeDashboardAgent"
    Write-Host "Done! Scheduled task created and started."
    Write-Host "  Get-ScheduledTask -TaskName ClaudeDashboardAgent"
    Write-Host "  Stop-ScheduledTask -TaskName ClaudeDashboardAgent"
    Write-Host "  Start-ScheduledTask -TaskName ClaudeDashboardAgent"
    Write-Host "  Unregister-ScheduledTask -TaskName ClaudeDashboardAgent   (to uninstall)"
}
