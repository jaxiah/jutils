$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$wt = Get-Command wt -ErrorAction SilentlyContinue
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue

if (-not $pwsh) {
    throw "pwsh not found in PATH."
}

function Start-UtilityPwshWindow {
    param(
        [string]$Title,
        [string]$ScriptPath,
        [string[]]$ExtraArgs = @()
    )

    $quotedScript = "'" + $ScriptPath.Replace("'", "''") + "'"
    $argText = if ($ExtraArgs.Count -gt 0) { ($ExtraArgs -join " ") + " " } else { "" }
    $command = "python ${argText}${quotedScript}"
    Start-Process -FilePath $pwsh.Source -WorkingDirectory $root -ArgumentList @("-NoExit", "-Command", $command) | Out-Null
}

function New-WtTab {
    param(
        [string]$Title,
        [string]$ScriptPath,
        [string[]]$ExtraArgs = @()
    )

    $quotedScript = "'" + $ScriptPath.Replace("'", "''") + "'"
    $argText = if ($ExtraArgs.Count -gt 0) { ($ExtraArgs -join " ") + " " } else { "" }
    $command = "python ${argText}${quotedScript}"

    $wtArgs = @(
        "-w",
        "0",
        "new-tab",
        "-d",
        $root,
        "--title",
        $Title,
        $pwsh.Source,
        "-NoExit",
        "-Command",
        $command
    )

    Start-Process -FilePath $wt.Source -ArgumentList $wtArgs | Out-Null
}

$pomoScript = Join-Path $root "pomo_debrief.py"
$codexScript = Join-Path $root "codex_auto_ping.py"

if (-not (Test-Path $pomoScript)) {
    throw "Missing script: $pomoScript"
}

if (-not (Test-Path $codexScript)) {
    throw "Missing script: $codexScript"
}

if ($wt) {
    New-WtTab -Title "pomo_debrief" -ScriptPath $pomoScript
    Start-Sleep -Milliseconds 800
    New-WtTab -Title "codex_auto_ping" -ScriptPath $codexScript -ExtraArgs @("-u")
    exit 0
}

Start-UtilityPwshWindow -Title "pomo_debrief" -ScriptPath $pomoScript
Start-UtilityPwshWindow -Title "codex_auto_ping" -ScriptPath $codexScript -ExtraArgs @("-u")
