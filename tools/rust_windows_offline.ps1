$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'The firewall boundary is restricted to this disposable GitHub-hosted Windows job'
}
$taskPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Native disconnected qualification needs the disposable runner administrator'
}
if ((Get-Service -Name mpssvc).Status -ne 'Running') { throw 'Windows Firewall service must already be running' }
$taskProfiles = @(Get-NetFirewallProfile | Select-Object Name, Enabled)
if ($taskProfiles.Count -ne 3) { throw 'Complete Windows firewall profile inventory required' }
$taskRuleName = 'foundation-rust-offline-' + [Guid]::NewGuid().ToString('N')
$taskStatus = 'failed'
$taskRestored = $false
$taskRule = $null
$taskError = $null
& python -B .github/scripts/rust_qualification.py windows-online-probe
if ($LASTEXITCODE -ne 0) { throw 'No positive external TCP control before the disposable boundary' }
try {
    Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled True
    # Preserve loopback used by tests; every non-loopback IPv4/IPv6 destination
    # is denied, including private-network and DNS/service endpoints.
    $taskRemote = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
    New-NetFirewallRule -Name $taskRuleName -DisplayName $taskRuleName -Direction Outbound -Action Block `
        -Enabled True -Profile Any -Protocol Any -RemoteAddress $taskRemote | Out-Null
    $taskRule = Get-NetFirewallRule -Name $taskRuleName | Select-Object Name, Enabled, Direction, Action, Profile
    if ($taskRule.Enabled -ne 'True' -or $taskRule.Direction -ne 'Outbound' -or $taskRule.Action -ne 'Block' `
        -or @(Get-NetFirewallProfile | Where-Object { $_.Enabled -ne 'True' }).Count -ne 0) {
        throw 'The disposable outbound boundary is not active'
    }
    $env:FOUNDATION_WINDOWS_OFFLINE_RULE = $taskRuleName
    & python -B .github/scripts/rust_qualification.py supervise-windows-offline
    if ($LASTEXITCODE -ne 0) { throw 'The bounded native disconnected command failed' }
    $taskStatus = 'passed'
} catch {
    $taskError = $_.Exception.Message
    throw
} finally {
    Remove-Item Env:FOUNDATION_WINDOWS_OFFLINE_RULE -ErrorAction SilentlyContinue
    if (Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -Name $taskRuleName
    }
    foreach ($taskProfile in $taskProfiles) {
        Set-NetFirewallProfile -Profile $taskProfile.Name -Enabled $taskProfile.Enabled
    }
    $taskAfter = @(Get-NetFirewallProfile | Select-Object Name, Enabled)
    $taskRestored = (-not (Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue)) `
        -and @(Compare-Object $taskProfiles $taskAfter -Property Name, Enabled).Count -eq 0
    $taskReceipt = @{ schema_version = 1; status = $taskStatus; restored = $taskRestored; rule = $taskRule;
        before_profiles = $taskProfiles; after_profiles = $taskAfter; error = $taskError; maximum_seconds = 600 }
    $taskDestination = [IO.Path]::GetFullPath('build/rust-windows-firewall.json')
    if (Test-Path -LiteralPath $taskDestination) { throw 'Firewall receipt must be a new attempt' }
    $taskReceipt | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $taskDestination -Encoding utf8NoBOM
    if (-not $taskRestored) { throw 'Original firewall profiles or temporary-rule removal could not be verified' }
}
