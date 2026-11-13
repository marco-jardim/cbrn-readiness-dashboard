<#
.SYNOPSIS
    Smoke test of the Inno Setup installer: silent install, frozen self-test, silent uninstall.

.DESCRIPTION
    Runs the setup file silently for the current user into a temporary folder, checks that
    cbrn-dashboard.exe is there and that portable.ini is not, runs the installed program with
    --self-test and --data-dir (exit code 0 and selftest.json with passed=true), runs the
    uninstaller silently and checks that the program folder is gone, the uninstall entry is gone
    and the data folder is still there.

    The release workflow runs this script on every version tag; the packaging tests run it too.
    It needs no administrator rights. It works with Windows PowerShell 5.1 and PowerShell 7.

    Exit codes: 0 = passed, 1 = failed, 2 = refused because this program is already installed on
    this computer for the current user (the test would replace that installation's uninstall
    entry; remove the installation first).

.PARAMETER Setup
    Path of the setup .exe.

.PARAMETER WorkDir
    Folder for the install, the data and the logs. Default: a new folder in the temp folder. It
    is deleted at the end unless -Keep is given.

.PARAMETER Keep
    Keep the work folder.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Setup,
    [string]$WorkDir = '',
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'

# The AppId of packaging/installer/cbrn-dashboard.iss (a test keeps the two equal).
$AppId = '{7C3F2A58-5E1B-4D6A-9B84-2F0D1C9E6A31}'
$UninstallKeyName = "$AppId" + '_is1'
$UninstallKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$UninstallKeyName",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$UninstallKeyName",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$UninstallKeyName"
)

function Test-Registered {
    foreach ($key in $UninstallKeys) {
        if (Test-Path -LiteralPath $key) { return $true }
    }
    return $false
}

function Write-Step([string]$Text) {
    Write-Host "== $Text"
}

function Wait-Until([scriptblock]$Condition, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return [bool](& $Condition)
}

if (-not (Test-Path -LiteralPath $Setup -PathType Leaf)) {
    Write-Error "The setup file does not exist: $Setup"
    exit 1
}
$Setup = (Resolve-Path -LiteralPath $Setup).Path

if (Test-Registered) {
    Write-Host 'REFUSED: the CBRN Readiness Dashboard is already installed on this computer.'
    Write-Host 'This test uses the same uninstall entry. Uninstall the program first.'
    exit 2
}

$ownWorkDir = $false
if (-not $WorkDir) {
    $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('cbrn-installer-smoke-' + [guid]::NewGuid().ToString('N'))
    $ownWorkDir = $true
}
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$WorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$installDir = Join-Path $WorkDir 'inst'
$dataDir = Join-Path $WorkDir 'data'
$setupLog = Join-Path $WorkDir 'setup.log'
$exe = Join-Path $installDir 'cbrn-dashboard.exe'
$uninstaller = Join-Path $installDir 'unins000.exe'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

if (-not $env:QT_QPA_PLATFORM) { $env:QT_QPA_PLATFORM = 'offscreen' }

$failed = $false
try {
    Write-Step "Silent install into $installDir"
    $setupArguments = @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
        "/DIR=`"$installDir`"", "/LOG=`"$setupLog`""
    )
    $install = Start-Process -FilePath $Setup -ArgumentList $setupArguments -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw "the setup exited with code $($install.ExitCode)" }
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "$exe was not installed" }
    if (-not (Test-Path -LiteralPath (Join-Path $installDir '_internal') -PathType Container)) {
        throw 'the _internal folder was not installed'
    }
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw "$uninstaller was not written" }
    if (Test-Path -LiteralPath (Join-Path $installDir 'portable.ini')) {
        throw 'portable.ini was installed: the program would switch to portable mode'
    }
    if (-not (Test-Registered)) { throw 'the uninstall entry was not written' }

    Write-Step 'Self-test of the installed program'
    $test = Start-Process -FilePath $exe -ArgumentList @('--self-test', '--data-dir', "`"$dataDir`"") -Wait -PassThru
    $resultFile = Join-Path $dataDir 'selftest.json'
    if (-not (Test-Path -LiteralPath $resultFile -PathType Leaf)) { throw 'the self-test wrote no selftest.json' }
    $resultText = Get-Content -LiteralPath $resultFile -Raw -Encoding UTF8
    Write-Host $resultText
    if ($test.ExitCode -ne 0) { throw "the self-test exited with code $($test.ExitCode)" }
    $result = $resultText | ConvertFrom-Json
    if ($result.passed -ne $true) { throw 'selftest.json says passed is not true' }

    Write-Step 'Silent uninstall'
    $remove = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
    if ($remove.ExitCode -ne 0) { throw "the uninstaller exited with code $($remove.ExitCode)" }
    # The uninstaller copies itself to a temporary place and starts that copy, so the process
    # started above can end before the files are gone: wait for the result.
    $gone = Wait-Until { -not (Test-Path -LiteralPath $installDir) } 120
    if (-not $gone) {
        $left = (Get-ChildItem -LiteralPath $installDir -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ', '
        throw "the program folder is still there after the uninstall: $left"
    }
    if (-not (Wait-Until { -not (Test-Registered) } 30)) { throw 'the uninstall entry is still there' }
    if (-not (Test-Path -LiteralPath $resultFile -PathType Leaf)) {
        throw 'the uninstall deleted the data folder'
    }
    Write-Host 'PASSED: install, self-test and uninstall; the data folder was kept.'
}
catch {
    $failed = $true
    Write-Host "FAILED: $($_.Exception.Message)"
    if (Test-Path -LiteralPath $setupLog) {
        Write-Host '---- setup.log ----'
        Get-Content -LiteralPath $setupLog | Select-Object -Last 60 | ForEach-Object { Write-Host $_ }
    }
}
finally {
    # Never leave a registration behind after a failure.
    if ($failed -and (Test-Path -LiteralPath $uninstaller)) {
        Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait | Out-Null
        Wait-Until { -not (Test-Path -LiteralPath $installDir) } 60 | Out-Null
    }
    if ($ownWorkDir -and -not $Keep) {
        Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($failed) { exit 1 }
exit 0
