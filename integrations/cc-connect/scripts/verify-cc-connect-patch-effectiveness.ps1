param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SourceDir = [IO.Path]::GetFullPath($SourceDir)
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$LockPath = Join-Path $RepoRoot "integrations\cc-connect\manifests\artifact-lock.json"
$ApplyScript = Join-Path $PSScriptRoot "apply-cc-connect-patches.ps1"
$Lock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$MutationRoot = [IO.Path]::GetFullPath((Join-Path $TempRoot ("aiad-cc-connect-mutation-" + [guid]::NewGuid().ToString("N"))))
if (-not $MutationRoot.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "mutation worktree escaped the temporary directory"
}

function Invoke-GitChecked {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "git failed: $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-PatchMutation {
    param(
        [string]$PatchId,
        [string]$RelativePath,
        [object[]]$Replacements,
        [string]$Package,
        [string]$TestName
    )

    $path = Join-Path $MutationRoot $RelativePath
    $original = [IO.File]::ReadAllBytes($path)
    try {
        $text = [Text.Encoding]::UTF8.GetString($original)
        foreach ($replacement in $Replacements) {
            $before = [string]$replacement.before
            $after = [string]$replacement.after
            $count = ([regex]::Matches($text, [regex]::Escape($before))).Count
            if ($count -ne 1) {
                throw "$PatchId mutation anchor count for '$before' was $count, expected 1"
            }
            $text = $text.Replace($before, $after)
        }
        [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))

        Push-Location -LiteralPath $MutationRoot
        try {
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $output = & go test -mod=readonly -tags "no_web goolm no_pi" $Package -run "^$TestName`$" -count=1 2>&1
                $exitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $previousPreference
            }
        }
        finally {
            Pop-Location
        }
        $joined = $output -join [Environment]::NewLine
        if ($exitCode -eq 0) {
            throw "$PatchId mutation unexpectedly passed $TestName"
        }
        if ($joined -notmatch [regex]::Escape("--- FAIL: $TestName")) {
            throw "$PatchId failed for an unexpected reason while running $TestName`n$joined"
        }
        return [ordered]@{
            patch = $PatchId
            test = $TestName
            mutation_detected = $true
        }
    }
    finally {
        [IO.File]::WriteAllBytes($path, $original)
    }
}

$worktreeAdded = $false
try {
    Invoke-GitChecked -Arguments @("-C", $SourceDir, "worktree", "add", "--detach", $MutationRoot, [string]$Lock.source_commit) | Out-Null
    $worktreeAdded = $true
    Invoke-GitChecked -Arguments @("-C", $MutationRoot, "config", "core.autocrlf", "false") | Out-Null
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ApplyScript -SourceDir $MutationRoot
    if ($LASTEXITCODE -ne 0) {
        throw "failed to apply the locked patchset in the mutation worktree"
    }

    $env:CGO_ENABLED = "0"
    $results = @(
        Invoke-PatchMutation `
            -PatchId "001" `
            -RelativePath "platform\telegram\telegram.go" `
            -Replacements @(
                @{ before = "if hasExplicitMention {"; after = "if hasExplicitMention && mentionsSelf {" }
            ) `
            -Package "./platform/telegram" `
            -TestName "TestIsDirectedAtBot"
        Invoke-PatchMutation `
            -PatchId "002" `
            -RelativePath "core\hooks.go" `
            -Replacements @(
                @{ before = "req.Header.Set(name, value)"; after = "if false { req.Header.Set(name, value) }" }
            ) `
            -Package "./core" `
            -TestName "TestEmit_HTTPHookCustomHeadersPreserveProtocolHeaders"
        Invoke-PatchMutation `
            -PatchId "003" `
            -RelativePath "core\relay.go" `
            -Replacements @(
                @{ before = "func relayVisibilityResponseLabel(mode, _ string, response string) string {"; after = "func relayVisibilityResponseLabel(mode, toName string, response string) string {" },
                @{ before = 'return fmt.Sprintf("relay response ready (%d chars)", len([]rune(response)))'; after = 'return fmt.Sprintf("[%s] relay response ready (%d chars)", toName, len([]rune(response)))' },
                @{ before = "return truncateRelay(response, 2000)"; after = 'return fmt.Sprintf("[%s] %s", toName, truncateRelay(response, 2000))' }
            ) `
            -Package "./core" `
            -TestName "TestRelayManager_DefaultVisibilityEchoesFullMessages"
        Invoke-PatchMutation `
            -PatchId "004" `
            -RelativePath "core\engine.go" `
            -Replacements @(
                @{ before = "e.emitSentDelivered(p, delivery)"; after = "_ = delivery" }
            ) `
            -Package "./core" `
            -TestName "TestEngineDeliveryReporterEmitsExactHook"
    )
    [ordered]@{
        status = "passed"
        source_commit = [string]$Lock.source_commit
        patchset_version = [string]$Lock.patchset_version
        results = $results
    } | ConvertTo-Json -Depth 5 -Compress
}
finally {
    if ($worktreeAdded) {
        & git -C $SourceDir worktree remove --force $MutationRoot 2>$null | Out-Null
    }
    if (Test-Path -LiteralPath $MutationRoot) {
        $resolved = [IO.Path]::GetFullPath($MutationRoot)
        if (-not $resolved.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to clean a mutation path outside the temporary directory"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
