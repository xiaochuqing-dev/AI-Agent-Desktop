# ============================================================================
# remove-junction.ps1
# 安全移除 junction（只删链接，不删目标目录的真实内容）。
# 用法:
#   powershell -ExecutionPolicy Bypass -File remove-junction.ps1
#   powershell -ExecutionPolicy Bypass -File remove-junction.ps1 -JunctionPath "C:\ai-agent-collaboration"
# 安全保证:
#   - 只对 LinkType==Junction 的项执行 rmdir（删除链接本身）
#   - 若是真实目录或文件，拒绝操作，避免误删数据
# ============================================================================
param(
  [string]$JunctionPath = "C:\ai-agent-collaboration"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $JunctionPath)) {
  Write-Host "junction 不存在，无需移除: $JunctionPath" -ForegroundColor Yellow
  exit 0
}

$item = Get-Item $JunctionPath -Force

if ($item.LinkType -ne 'Junction') {
  Write-Error "$JunctionPath 不是 junction (LinkType=$($item.LinkType))，拒绝移除以防误删真实目录。"
  Write-Error "如确需删除，请手动确认后操作。"
  exit 1
}

# junction 用 rmdir 删除只移除链接，不影响目标
cmd /c rmdir "$JunctionPath" 2>&1 | Out-Null

if (-not (Test-Path $JunctionPath)) {
  Write-Host "junction 已移除: $JunctionPath" -ForegroundColor Green
  Write-Host "  (目标真实目录未受影响)"
  # 顺便提示环境变量
  if ($env:AI_AGENT_COLLAB_ROOT -eq $JunctionPath) {
    Write-Host "  注意: AI_AGENT_COLLAB_ROOT 仍指向此路径，需同步清理 Hermes_Gateway.vbs。" -ForegroundColor Yellow
  }
  exit 0
} else {
  Write-Error "移除失败，可能需管理员权限: $JunctionPath"
  exit 1
}
