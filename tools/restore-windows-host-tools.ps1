# Explicit one-time bootstrap from already-retained ZIPs. No downloads or tool execution.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonArchive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$PythonSha256,
    [Parameter(Mandatory=$true)][string]$CmakeArchive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$CmakeSha256,
    [Parameter(Mandatory=$true)][string]$NinjaArchive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$NinjaSha256,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'This bootstrap requires native Windows.' }
# .NET's process working directory can differ from PowerShell Set-Location.
# Restrict this bootstrap to fully qualified local paths, including the output.
foreach ($path in @($PythonArchive, $CmakeArchive, $NinjaArchive, $Output)) {
    if ($path -notmatch '^[A-Za-z]:[\\/]') { throw 'Use absolute local Windows paths (for example C:\owned\tools).' }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-OrdinaryPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked bootstrap paths are unsupported.' }
        if ($item -is [IO.DirectoryInfo]) { $item = $item.Parent } else { $item = $item.Directory }
    }
}

function Expand-CheckedZip([string]$Archive, [string]$Expected, [string]$Destination) {
    Assert-OrdinaryPath $Archive
    # Keep the exact checked input open without permitting writes or deletion.
    $stream = [IO.File]::Open($Archive, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $zip = $null
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $actual = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
        if ($actual -cne $Expected.ToLowerInvariant()) { throw 'Retained ZIP SHA256 mismatch.' }
        $stream.Position = 0
        $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read, $true)
        $entries = [Collections.Generic.Dictionary[string,bool]]::new([StringComparer]::OrdinalIgnoreCase)
        $spellings = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase)
        if ($zip.Entries.Count -gt 50000) { throw 'Bootstrap ZIP has too many entries.' }
        [long]$expanded = 0
        foreach ($entry in $zip.Entries) {
            $expanded += $entry.Length
            if ($expanded -gt 2GB) { throw 'Bootstrap ZIP expanded size exceeds 2 GiB.' }
            $name = $entry.FullName
            $directory = $name.EndsWith('/')
            $path = $name.TrimEnd('/')
            $mode = ($entry.ExternalAttributes -shr 16) -band 0xffff
            if (-not $path -or $name.Contains('\') -or $name.EndsWith('//') -or
                (($mode -band 0xf000) -notin @(0, 0x8000, 0x4000)) -or ($mode -band 0xe00) -or
                ($entry.ExternalAttributes -band 0x400) -or
                (($mode -band 0xf000) -eq 0x4000 -and -not $directory)) {
                throw 'Unsafe or linked ZIP member.'
            }
            $prefix = ''
            foreach ($part in $path.Split('/')) {
                if (-not $part -or $part -in @('.', '..') -or $part -match '[\x00-\x1f\x7f<>:"|?*]' -or
                    $part -match '[. ]$' -or $part -match '^(?i:con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3])(?:\.|$)') {
                    throw 'Unsafe Windows ZIP path.'
                }
                if ($prefix) { $prefix += '/' }
                $prefix += $part
                if ($spellings.ContainsKey($prefix) -and $spellings[$prefix] -cne $prefix) {
                    throw 'Inconsistent explicit or implicit ZIP path spelling.'
                }
                $spellings[$prefix] = $prefix
            }
            if ($entries.ContainsKey($path)) { throw 'Duplicate or case-colliding ZIP member.' }
            $entries.Add($path, $directory)
        }
        if (-not $entries.Count) { throw 'Empty bootstrap ZIP.' }
        foreach ($path in $entries.Keys) {
            $parent = $path
            while ($parent.Contains('/')) {
                $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
                if ($entries.ContainsKey($parent) -and -not $entries[$parent]) { throw 'ZIP file is an ancestor.' }
            }
        }
        [IO.Directory]::CreateDirectory($Destination) | Out-Null
        foreach ($entry in $zip.Entries) {
            $target = Join-Path $Destination $entry.FullName.TrimEnd('/')
            if ($entry.FullName.EndsWith('/')) { [IO.Directory]::CreateDirectory($target) | Out-Null; continue }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            $inputStream = $entry.Open()
            try {
                $outputStream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
                try {
                    $buffer = [byte[]]::new(65536)
                    [long]$written = 0
                    while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $written += $count
                        if ($written -gt $entry.Length) { throw 'ZIP member exceeds declared size.' }
                        $outputStream.Write($buffer, 0, $count)
                    }
                    if ($written -ne $entry.Length) { throw 'ZIP member size mismatch.' }
                } finally { $outputStream.Dispose() }
            } finally { $inputStream.Dispose() }
        }
    } finally {
        if ($null -ne $zip) { $zip.Dispose() }
        $stream.Dispose()
    }
}

$outputPath = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) { throw 'Bootstrap output must be new.' }
$parent = [IO.Path]::GetDirectoryName($outputPath)
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Create and exclusively own the bootstrap parent directory first.' }
Assert-OrdinaryPath $parent
$stage = Join-Path $parent ('.windows-tools-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage) | Out-Null
try {
    Expand-CheckedZip ([IO.Path]::GetFullPath($PythonArchive)) $PythonSha256 (Join-Path $stage 'python')
    Expand-CheckedZip ([IO.Path]::GetFullPath($CmakeArchive)) $CmakeSha256 (Join-Path $stage 'cmake')
    Expand-CheckedZip ([IO.Path]::GetFullPath($NinjaArchive)) $NinjaSha256 (Join-Path $stage 'ninja')
    $policies = @(Get-ChildItem -LiteralPath (Join-Path $stage 'python') -Filter 'python*._pth' -File)
    $cmakeRoots = @(Get-ChildItem -LiteralPath (Join-Path $stage 'cmake') -Directory |
        Where-Object { $_.Name -match '^cmake-[0-9]+\.[0-9]+\.[0-9]+-windows-x86_64$' })
    if ($policies.Count -ne 1 -or $policies[0].Name -notmatch '^python[0-9]+\._pth$' -or $cmakeRoots.Count -ne 1) {
        throw 'Unexpected retained Python or CMake layout.'
    }
    $cmakeRelative = 'cmake/' + $cmakeRoots[0].Name + '/bin'
    foreach ($name in @('python/python.exe', 'ninja/ninja.exe', "$cmakeRelative/cmake.exe", "$cmakeRelative/ctest.exe", "$cmakeRelative/cpack.exe")) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $name) -PathType Leaf)) { throw "Missing retained host tool: $name" }
    }
    $policy = $policies[0]
    $stem = [IO.Path]::GetFileNameWithoutExtension($policy.Name)
    $searchPaths = @([IO.File]::ReadAllLines($policy.FullName) | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') })
    if ($searchPaths.Count -ne 2 -or $searchPaths[0] -cne ($stem + '.zip') -or $searchPaths[1] -cne '.' -or
        -not (Test-Path -LiteralPath (Join-Path $stage ('python/' + $stem + '.zip')) -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $stage ('python/' + $stem + '.dll')) -PathType Leaf)) {
        throw 'Unexpected embedded Python search policy or standard-library layout.'
    }
    # Retain the exact isolated policy but restore normal Python initialization,
    # including the invoked script directory needed for local helper imports.
    # The embedded standard-library ZIP and DLL are preserved unchanged.
    [IO.File]::Move($policies[0].FullName, $policies[0].FullName + '.retained-disabled')
    $receipt = [ordered]@{ schema_version = 1; scope = 'host-tool-bootstrap'; qualification = 'not-executed';
        archives = @{ python = $PythonSha256.ToLowerInvariant(); cmake = $CmakeSha256.ToLowerInvariant(); ninja = $NinjaSha256.ToLowerInvariant() };
        python = 'python/python.exe'; cmake_bin = $cmakeRelative; ninja_bin = 'ninja';
        separate_prerequisites = @('Microsoft compiler and Windows SDK', 'Git for checkout and Git-dependent tests') }
    [IO.File]::WriteAllText((Join-Path $stage 'bootstrap.json'), ($receipt | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    [IO.Directory]::Move($stage, $outputPath)
    $receipt | ConvertTo-Json -Depth 4
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
