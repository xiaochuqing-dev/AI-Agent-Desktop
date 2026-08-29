param(
    [string]$OutputDir = "",
    [Parameter(Mandatory = $true)]
    [string]$CcConnectBundle,
    [switch]$Clean,
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ControlPlaneRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ControlPlaneRoot "dist\AI-Agent-Desktop-gui-windows-x64"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$CcConnectBundle = [IO.Path]::GetFullPath($CcConnectBundle)
$BuildRoot = Join-Path $ControlPlaneRoot "build\windows-candidate"
$LocalPython = Join-Path $ControlPlaneRoot ".venv\Scripts\python.exe"
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
        $PythonExe = $LocalPython
    }
    else {
        $PythonExe = (Get-Command python.exe -ErrorAction Stop).Source
    }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
$VerifyScript = Join-Path $ControlPlaneRoot "..\integrations\cc-connect\scripts\verify-cc-connect-artifact.ps1"
$VerifyLock = Join-Path $ControlPlaneRoot "..\integrations\cc-connect\manifests\artifact-lock.json"
$ControlPlaneLock = Join-Path $ControlPlaneRoot "control_plane\installer\artifact-lock.json"

if (-not (Test-Path -LiteralPath $CcConnectBundle -PathType Container)) {
    throw "cc-connect bundle directory does not exist: $CcConnectBundle"
}
if (-not (Test-Path -LiteralPath $VerifyScript -PathType Leaf)) {
    throw "cc-connect verifier is missing: $VerifyScript"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python executable does not exist: $PythonExe"
}
if ((Get-FileHash -LiteralPath $VerifyLock -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $ControlPlaneLock -Algorithm SHA256).Hash) {
    throw "integration and Control Plane artifact locks differ"
}
$PythonVersion = (& $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
if ($PythonVersion -ne "3.12.10") {
    throw "candidate builds require Python 3.12.10; found $PythonVersion ($PythonExe)"
}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $VerifyScript -BundleDir $CcConnectBundle -LockFile $VerifyLock
if ($LASTEXITCODE -ne 0) { throw "cc-connect artifact verification failed" }

if ($Clean -and (Test-Path -LiteralPath $BuildRoot)) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "AI-Agent-Desktop" `
    --distpath $BuildRoot `
    --workpath (Join-Path $BuildRoot "work") `
    --specpath (Join-Path $BuildRoot "spec") `
    --paths $ControlPlaneRoot `
    --add-data "$ControlPlaneRoot\alembic;alembic" `
    --add-data "$ControlPlaneRoot\alembic.ini;." `
    --add-data "$ControlPlaneRoot\control_plane\gui\assets;control_plane/gui/assets" `
    --add-data "$ControlPlaneRoot\control_plane\gui\icons\assets;control_plane/gui/icons/assets" `
    --icon "$ControlPlaneRoot\control_plane\gui\assets\app_icon.ico" `
    --collect-data control_plane `
    --hidden-import control_plane.main `
    --hidden-import control_plane.gui `
    --hidden-import control_plane.gui.app `
    --hidden-import qrcode `
    --hidden-import qrcode.image.pil `
    --hidden-import keyring.backends.Windows `
    (Join-Path $PSScriptRoot "gui_candidate_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Built = Join-Path $BuildRoot "AI-Agent-Desktop.exe"
if (-not (Test-Path -LiteralPath $Built -PathType Leaf)) { throw "PyInstaller output missing: $Built" }
Copy-Item -LiteralPath $Built -Destination (Join-Path $OutputDir "AI-Agent-Desktop.exe") -Force

$CcOutput = Join-Path $OutputDir "cc-connect"
New-Item -ItemType Directory -Force -Path $CcOutput | Out-Null
foreach ($name in @("cc-connect.exe", "cc-connect-artifact-manifest.json", "cc-connect.sha256")) {
    $source = Join-Path $CcConnectBundle $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "cc-connect bundle file is missing: $name"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $CcOutput $name) -Force
}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $VerifyScript -BundleDir $CcOutput -LockFile $VerifyLock
if ($LASTEXITCODE -ne 0) { throw "copied cc-connect artifact verification failed" }

Copy-Item -LiteralPath (Join-Path $PSScriptRoot "production_only_acceptance.py") -Destination $OutputDir -Force
Copy-Item -LiteralPath (Join-Path $ControlPlaneRoot "requirements-prod.lock") -Destination $OutputDir -Force
Copy-Item -LiteralPath (Join-Path $ControlPlaneRoot "requirements-build.lock") -Destination $OutputDir -Force
Copy-Item -LiteralPath (Join-Path $ControlPlaneRoot "requirements-gui.lock") -Destination $OutputDir -Force
Copy-Item -LiteralPath (Join-Path $ControlPlaneRoot ".python-version") -Destination $OutputDir -Force
Copy-Item -LiteralPath $ControlPlaneLock -Destination (Join-Path $OutputDir "artifact-lock.json") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "windows10_user_acceptance.ps1") -Destination $OutputDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "USER_VALIDATION_GUIDE.txt") -Destination $OutputDir -Force

function Get-FileEntry {
    param([string]$Root, [System.IO.FileInfo]$File)
    $relative = $File.FullName.Substring($Root.Length).TrimStart('\')
    [ordered]@{
        path = $relative
        size = $File.Length
        sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$CandidateVersion = "0.4.1-prebeta"
$CcManifest = Get-Content -LiteralPath (Join-Path $CcOutput "cc-connect-artifact-manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$CcLock = Get-Content -LiteralPath $ControlPlaneLock -Raw -Encoding UTF8 | ConvertFrom-Json
Push-Location -LiteralPath $ControlPlaneRoot
try {
    $RendererFactsOutput = & $PythonExe -c 'import json; from control_plane.cc_connect.native_config_renderer import CcConnectNativeConfigRenderer; value = CcConnectNativeConfigRenderer().capability(); print(json.dumps(dict(renderer_version=value.renderer_version, source_commit=value.source_commit), sort_keys=True))'
    if ($LASTEXITCODE -ne 0) { throw "failed to read native renderer release facts" }
    $RendererFactsJson = ($RendererFactsOutput -join "").Trim()
}
finally {
    Pop-Location
}
$RendererFacts = $RendererFactsJson | ConvertFrom-Json
if ([string]$RendererFacts.source_commit -ne [string]$CcLock.source_commit) {
    throw "native renderer source commit does not match the artifact lock"
}
$CcSha = (Get-Content -LiteralPath (Join-Path $CcOutput "cc-connect.sha256") -Raw -Encoding UTF8).Trim().Split(' ')[0].ToLowerInvariant()
$PayloadFiles = @(Get-ChildItem -LiteralPath $OutputDir -Recurse -File | Where-Object {
    $_.Name -notin @("candidate-manifest.json", "candidate-manifest.sha256", "SHA256SUMS.txt", "candidate-package.sha256")
} | Sort-Object FullName)
$Entries = @($PayloadFiles | ForEach-Object { Get-FileEntry -Root $OutputDir -File $_ })
$Canonical = (($Entries | ForEach-Object { "{0}  {1}" -f $_.sha256, $_.path }) -join "`n") + "`n"
$HashAlgorithm = [Security.Cryptography.SHA256]::Create()
try {
    $PackageHash = ([BitConverter]::ToString($HashAlgorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Canonical))).Replace("-", "")).ToLowerInvariant()
}
finally {
    $HashAlgorithm.Dispose()
}
$Manifest = [ordered]@{
    schema_version = "1"
    candidate_version = $CandidateVersion
    product = "AI-Agent-Desktop"
    platform = "windows"
    architecture = "x64"
    minimum_os = "Windows 10"
    python_embedded = $true
    go_embedded = $false
    node_embedded = $false
    black_window = $false
    changes_external_environment = $false
    chrome_agent_required = $false
    cc_connect_artifact_id = [string]$CcManifest.artifact_id
    cc_connect_version = [string]$CcManifest.version
    cc_connect_source_commit = [string]$CcManifest.source_commit
    cc_connect_patchset_version = [string]$CcManifest.patchset_version
    cc_connect_active_patch_count = @($CcManifest.patch_files).Count
    cc_connect_artifact_sha256 = $CcSha
    cc_connect_renderer_version = [string]$RendererFacts.renderer_version
    cc_connect_renderer_source_commit = [string]$RendererFacts.source_commit
    package_sha256 = $PackageHash
    package_sha256_basis = "UTF-8 SHA256 of sorted payload '<sha256>  <relative path>' lines"
    files = $Entries
}
$ManifestPath = Join-Path $OutputDir "candidate-manifest.json"
$Manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
$ManifestHash = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $OutputDir "candidate-manifest.sha256") -Value "$ManifestHash  candidate-manifest.json" -Encoding ASCII
Set-Content -LiteralPath (Join-Path $OutputDir "candidate-package.sha256") -Value "$PackageHash  payload" -Encoding ASCII

$All = Get-ChildItem -LiteralPath $OutputDir -Recurse -File | Where-Object {
    $_.Name -ne "SHA256SUMS.txt"
} | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($OutputDir.Length).TrimStart('\')
    "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $relative
}
$All | Set-Content -LiteralPath (Join-Path $OutputDir "SHA256SUMS.txt") -Encoding ASCII
Write-Output ("candidate={0}" -f $OutputDir)
Write-Output ("candidate_version={0}" -f $CandidateVersion)
Write-Output ("manifest_sha256={0}" -f $ManifestHash)
Write-Output ("package_sha256={0}" -f $PackageHash)
Write-Output ("cc_connect_sha256={0}" -f $CcSha)
