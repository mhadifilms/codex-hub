param([string]$Distribution = "Ubuntu", [switch]$NoBootstrap)
$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "Install WSL first: run 'wsl --install' in an administrator PowerShell, restart, and finish Ubuntu setup."
}
$LinuxSource = & wsl.exe --distribution $Distribution --exec wslpath -u ($PSScriptRoot.Replace('\', '/'))
if ($LASTEXITCODE -ne 0 -or -not $LinuxSource) {
    throw "Start $Distribution once to finish its user setup, then rerun install.ps1. See https://learn.microsoft.com/windows/wsl/install."
}
$LinuxInstaller = $LinuxSource.TrimEnd('/') + '/install.sh'
if ($NoBootstrap) {
    & wsl.exe --distribution $Distribution --exec sh $LinuxInstaller
} else {
    & wsl.exe --distribution $Distribution --exec sh $LinuxInstaller --bootstrap
}
if ($LASTEXITCODE -ne 0) { throw "Codex Hub installation failed; review the error above." }
Write-Host "Installed in $Distribution. Open its Windows Terminal tab and run ~/.local/bin/codex-hub."
