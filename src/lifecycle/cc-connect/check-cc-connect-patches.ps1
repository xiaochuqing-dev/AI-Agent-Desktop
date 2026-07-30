# ============================================================================
# check-cc-connect-patches.ps1
# 检查 cc-connect Patch 集能否干净应用到指定源码副本（不实际修改）。
# 用法:
#   powershell -ExecutionPolicy Bypass -File check-cc-connect-patches.ps1 `
#     -SourceDir "C:\path\to\cc-connect-src"
# 前提: SourceDir 是 cc-connect 在 fc315d2 的干净 clone。
# 退出码: 0 全部通过, 1 任一失败。
# ============================================================================
param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,
  [string]$PatchDir = (Join-Path $PSScriptRoot "..\..\..\patches\cc-connect")
)

$ErrorActionPreference = "Stop"
$patches = @(
  "001-telegram-directed-routing",
  "002-hook-config-headers",
  "003-relay-response-prefix",
  "004-message-delivery-hooks",
  "005-windows-build-compat"
)

Write-Host "=== 检查 Patch 可应用性 ===" -ForegroundColor Cyan
Write-Host "源码: $SourceDir"
Write-Host "Patch: $PatchDir"
Write-Host ""

if (-not (Test-Path (Join-Path $SourceDir ".git"))) {
  Write-Error "$SourceDir 不是 git 仓库"
  exit 1
}

Push-Location $SourceDir
try {
  # 行尾归一化：确保工作树为 LF（上游 blob 是 LF，autocrlf=true 会转 CRLF 导致 patch 不匹配）
  git config core.autocrlf false | Out-Null
  $dirty = git status --porcelain 2>&1
  if ($dirty) {
    Write-Host "源码工作树非干净，先还原..." -ForegroundColor Yellow
    git checkout -- . 2>&1 | Out-Null
  }
  # 重新 checkout 为 LF
  git ls-files -z | ForEach-Object { $_ } | Out-Null
  git checkout HEAD -- . 2>&1 | Out-Null

  $allOk = $true
  foreach ($p in $patches) {
    $patchFile = Join-Path $PatchDir "$p.patch"
    if (-not (Test-Path $patchFile)) {
      Write-Host "  [FAIL] $p : 文件不存在 $patchFile" -ForegroundColor Red
      $allOk = $false
      continue
    }
    $output = git apply --check $patchFile 2>&1
    if ($LASTEXITCODE -eq 0) {
      Write-Host "  [ OK ] $p" -ForegroundColor Green
    } else {
      Write-Host "  [FAIL] $p : $output" -ForegroundColor Red
      $allOk = $false
    }
  }

  Write-Host ""
  if ($allOk) {
    Write-Host "==> 全部 Patch 可应用" -ForegroundColor Green
    exit 0
  } else {
    Write-Host "==> 存在不可应用的 Patch" -ForegroundColor Red
    exit 1
  }
} finally {
  Pop-Location
}
