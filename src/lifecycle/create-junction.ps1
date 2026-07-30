# ============================================================================
# create-junction.ps1
# 重新创建 junction，绕过 vbs 中文路径被 GBK 解码成乱码的问题。
# 用法:
#   powershell -ExecutionPolicy Bypass -File create-junction.ps1 `
#     -ProjectRoot "C:\Users\<WINDOWS_USER>\...\ai-agent-collaboration" `
#     [-JunctionPath "C:\ai-agent-collaboration"]
# 注意: 本脚本只创建 junction，不修改项目目录内容。
# ============================================================================
param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot,
  [string]$JunctionPath = "C:\ai-agent-collaboration"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ProjectRoot)) {
  Write-Error "项目根目录不存在: $ProjectRoot"
  exit 1
}

# 转为绝对路径
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

if (Test-Path $JunctionPath) {
  $item = Get-Item $JunctionPath -Force
  if ($item.LinkType -eq 'Junction') {
    Write-Host "junction 已存在，先移除: $JunctionPath"
    $item.Delete()
  } elseif ($item.PSIsContainer) {
    Write-Error "$JunctionPath 是真实目录而非 junction，拒绝覆盖。请手动确认后重命名或删除。"
    exit 1
  } else {
    Write-Error "$JunctionPath 已存在且非 junction，请检查: $($item.LinkType)"
    exit 1
  }
}

# mklink /J 创建 junction (目录联接)
cmd /c mklink /J "$JunctionPath" "$ProjectRoot" | Out-Null

if ($LASTEXITCODE -eq 0 -and (Test-Path $JunctionPath)) {
  $check = Get-Item $JunctionPath -Force
  if ($check.LinkType -eq 'Junction' -and $check.Target -eq $ProjectRoot) {
    Write-Host "junction 创建成功" -ForegroundColor Green
    Write-Host "  链接 : $JunctionPath"
    Write-Host "  目标 : $ProjectRoot"
  } else {
    Write-Error "junction 已建但校验失败 (LinkType=$($check.LinkType), Target=$($check.Target))"
    exit 1
  }
} else {
  Write-Error "mklink 失败 (exit $LASTEXITCODE)，可能需要管理员权限"
  exit 1
}
