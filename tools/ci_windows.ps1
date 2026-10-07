param([string]$MinimumLinker = '', [string]$Output = 'build/windows-toolchain.json')
$ErrorActionPreference = 'Stop'
$chosen = & (Join-Path $PSScriptRoot 'select-windows-toolchain.ps1') -MinimumLinker $MinimumLinker
$setup = Join-Path $chosen.InstallationPath 'VC/Auxiliary/Build/vcvars64.bat'
$environment = & cmd.exe /d /s /c "`"$setup`" $($chosen.WindowsSdk) -vcvars_ver=$($chosen.ToolsVersion) >nul && set"
if ($LASTEXITCODE -ne 0) { throw 'Pinned MSVC environment setup failed' }
foreach ($line in $environment) {
    if ($line -match '^([^=]+)=(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2]
        # Export only the compiler environment. Copying every inherited variable
        # would unnecessarily expose unrelated environment values in later logs.
        if ($name -notmatch '^(PATH|INCLUDE|LIB|LIBPATH|EXTERNAL_INCLUDE|VC.*|VS.*|WindowsSdk.*|WindowsSDK.*|WindowsLibPath|UniversalCRTSdkDir|UCRTVersion|Framework.*|NETFXSDKDir|ExtensionSdkDir|DevEnvDir|CommandPromptType|Platform|PreferredToolArchitecture)$') { continue }
        if ($value.Contains("`n") -or $value.Contains("`r")) { throw 'Multiline compiler environment value rejected' }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        if ($env:GITHUB_ENV) { "$name=$value" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append }
    }
}
$destination = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
if (Test-Path -LiteralPath $destination) { throw 'Toolchain receipt must be a new attempt' }
$chosen | ConvertTo-Json | Out-File -LiteralPath $destination -Encoding utf8NoBOM
$chosen | ConvertTo-Json -Compress
