param(
    [string]$Policy = (Join-Path $PSScriptRoot '../third_party/sdk/windows-toolchain.json'),
    [string]$MinimumLinker = ''
)
$ErrorActionPreference = 'Stop'
$policyData = Get-Content -Raw -LiteralPath $Policy | ConvertFrom-Json
if ($policyData.schema_version -ne 1 -or $policyData.toolset -ne 'v143' -or $policyData.architecture -ne 'x64') {
    throw 'Unsupported Windows toolchain policy'
}
$selector = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not (Test-Path -LiteralPath $selector)) { throw 'Install a supported Visual Studio Build Tools environment first' }
$instances = & $selector -all -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Toolchain inventory failed' }
$candidates = @()
foreach ($instance in $instances) {
    if (-not $instance.isComplete) { continue }
    $major = ([version]$instance.installationVersion).Major
    if ($major -notin @(17, 18)) { continue }
    $directory = Join-Path $instance.installationPath 'VC/Tools/MSVC'
    if (-not (Test-Path -LiteralPath $directory)) { continue }
    foreach ($versionDirectory in Get-ChildItem -LiteralPath $directory -Directory) {
        if ($versionDirectory.Name -notmatch '^14\.[34]\d\.\d+$') { continue }
        $compiler = Join-Path $versionDirectory.FullName 'bin/Hostx64/x64/cl.exe'
        $linker = Join-Path $versionDirectory.FullName 'bin/Hostx64/x64/link.exe'
        if (-not (Test-Path -LiteralPath $compiler) -or -not (Test-Path -LiteralPath $linker)) { continue }
        $linkerVersion = (Get-Item -LiteralPath $linker).VersionInfo.FileVersion -replace ', ', '.'
        if ($MinimumLinker -and ([version]$linkerVersion -lt [version]$MinimumLinker)) { continue }
        $candidates += [pscustomobject]@{ Instance=$instance; Major=$major; Version=[version]$versionDirectory.Name; Compiler=$compiler; Linker=$linker; LinkerVersion=$linkerVersion }
    }
}
$chosen = $candidates | Sort-Object @{Expression={$_.Major};Descending=$false}, @{Expression={$_.Version};Descending=$true} | Select-Object -First 1
if (-not $chosen) { throw 'No installed v143 toolchain satisfies the retained dependency linker requirement' }
$kitRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
$kitVersion = $policyData.windows_sdk
$requiredKitFiles = @(
    "Include/$kitVersion/um/Windows.h", "Include/$kitVersion/shared/sdkddkver.h",
    "Include/$kitVersion/ucrt/stdio.h", "Lib/$kitVersion/um/x64/kernel32.lib",
    "Lib/$kitVersion/ucrt/x64/ucrt.lib", "bin/$kitVersion/x64/rc.exe", "bin/$kitVersion/x64/mt.exe"
)
foreach ($relative in $requiredKitFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $kitRoot $relative) -PathType Leaf)) {
        throw "The pinned Windows SDK $kitVersion is incomplete: $relative"
    }
}
[pscustomobject]@{
    InstallationPath=$chosen.Instance.installationPath
    Toolset=$policyData.toolset
    ToolsVersion=$chosen.Version.ToString()
    WindowsSdk=$kitVersion
    Compiler=$chosen.Compiler
    Linker=$chosen.Linker
    LinkerVersion=$chosen.LinkerVersion
    Runtime=$policyData.runtime
}
