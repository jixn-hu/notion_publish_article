param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Server,

    [ValidateNotNullOrEmpty()]
    [string]$User = "root",

    [ValidateRange(1, 65535)]
    [int]$LocalPort = 8701,

    [ValidateRange(1, 65535)]
    [int]$RemotePort = 8701,

    [string]$IdentityFile = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "OpenSSH client was not found. Install Windows OpenSSH Client first."
}

$sshArgs = @(
    "-N",
    "-T",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", ("{0}:127.0.0.1:{1}" -f $LocalPort, $RemotePort)
)

if ($IdentityFile) {
    $resolvedIdentity = (Resolve-Path -LiteralPath $IdentityFile).Path
    $sshArgs += @("-i", $resolvedIdentity)
}

$sshArgs += ("{0}@{1}" -f $User, $Server)

Write-Host ("MoFlow WeChat relay: http://127.0.0.1:{0}/wechat" -f $LocalPort)
Write-Host "Press Ctrl+C to stop the SSH tunnel."
& ssh @sshArgs

if ($LASTEXITCODE -ne 0) {
    throw "SSH tunnel exited with code $LASTEXITCODE."
}
