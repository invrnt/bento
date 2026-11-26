# Builds llama-server (smart search embedding runtime, decision D4) from the pinned llama.cpp source on
# Windows. Same pin, flags and output layout as scripts/build-llama-server.sh; keep both in step
# (docs/dev/smart-search.md). Run it from a "Developer PowerShell for VS" (MSVC on PATH); on arm64 it
# needs LLVM clang on PATH, like the official release.
#
#   scripts/build-llama-server.ps1 [-Out DIR] [-SourceTarball FILE] [-Cache DIR] [-Jobs N] [-Force]
#   scripts/build-llama-server.ps1 -PrintTarget      prints win32-x64 or win32-arm64 and exits
#   scripts/build-llama-server.ps1 -PrintLicenses    prints the bundled third-party components and exits
#
# Output: dist/llama-server/win32-<arch>/ with llama-server.exe, its DLLs (llama, ggml*, mtmd and the
# CPU backend variants), licenses/, bento-llama-server.json and SHA256SUMS.
[CmdletBinding()]
param(
  [string]$Out = "",
  [string]$SourceTarball = "",
  [string]$Cache = "",
  [int]$Jobs = 0,
  [switch]$Force,
  [switch]$PrintTarget,
  [switch]$PrintLicenses
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$LlamaCppTag = "b12777"
$LlamaCppBuildNumber = "12777"
$LlamaCppCommit = "caea914e9"
$LlamaCppSourceUrl = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/$LlamaCppTag.tar.gz"
$LlamaCppSourceSha256 = "d7f875b82ebda0b88ac5229d3deff3e53239a08030ce5aa6f7ce358fc219cd8c"

$Root = Split-Path -Parent $PSScriptRoot

function Fail([string]$Message) { throw "build-llama-server: $Message" }
function Say([string]$Message) { [Console]::Error.WriteLine("build-llama-server: $Message") }

function Get-HostTarget {
  $arch = $env:PROCESSOR_ARCHITEW6432
  if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
  switch ($arch) {
    "AMD64" { return "win32-x64" }
    "ARM64" { return "win32-arm64" }
    default { Fail "unsupported architecture: $arch" }
  }
}

function Get-Licenses {
  @(
    "llama.cpp (ggml-org) | MIT | licenses/LICENSE-llama.cpp",
    "cpp-httplib (yhirose) | MIT | licenses/LICENSE-cpp-httplib",
    "nlohmann/json (Niels Lohmann) | MIT | licenses/LICENSE-nlohmann-json",
    "xxHash (Yann Collet) | BSD-2-Clause | licenses/LICENSE-xxhash",
    "rotate-bits (William Casarin) | MIT | licenses/LICENSE-rotate-bits",
    "sha256 (Igor Pavlov) and sha1 (Steve Reid) | public domain | licenses/LICENSE-sha256",
    "miniaudio (David Reid) | public domain or MIT-0 | in miniaudio.h",
    "stb_image (Sean Barrett) | public domain or MIT | in stb_image.h",
    "subprocess.h (sheredom) | Unlicense | in subprocess.h"
  )
}

function Get-Sha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }

$Target = Get-HostTarget
if ($PrintTarget) { Write-Output $Target; exit 0 }
if ($PrintLicenses) { Get-Licenses | Write-Output; exit 0 }

if (-not $Out) { $Out = Join-Path $Root "dist\llama-server\$Target" }
if (-not $Cache) {
  $Cache = if ($env:BENTO_LLAMA_CACHE) { $env:BENTO_LLAMA_CACHE } else { Join-Path $env:LOCALAPPDATA "bento\cache\llama.cpp" }
}
if ($Jobs -le 0) { $Jobs = [Environment]::ProcessorCount }

# OpenMP stays off so no vcomp/libomp DLL must ship; OpenSSL, the web UI and llama-connect are off because
# Bento runs the server --offline on loopback. arm64 has no CPU variants on Windows (upstream does the same).
$CmakeArgs = @(
  "-DCMAKE_BUILD_TYPE=Release",
  "-DBUILD_SHARED_LIBS=ON",
  "-DLLAMA_BUILD_NUMBER=$LlamaCppBuildNumber",
  "-DLLAMA_BUILD_COMMIT=$LlamaCppCommit",
  "-DLLAMA_BUILD_TESTS=OFF",
  "-DLLAMA_BUILD_EXAMPLES=OFF",
  "-DLLAMA_BUILD_TOOLS=ON",
  "-DLLAMA_BUILD_SERVER=ON",
  "-DLLAMA_BUILD_UI=OFF",
  "-DLLAMA_USE_PREBUILT_UI=OFF",
  "-DLLAMA_CONNECT=OFF",
  "-DLLAMA_OPENSSL=OFF",
  "-DGGML_OPENMP=OFF",
  "-DGGML_NATIVE=OFF",
  "-DGGML_BACKEND_DL=ON"
)
if ($Target -eq "win32-x64") { $CmakeArgs += "-DGGML_CPU_ALL_VARIANTS=ON" } else { $CmakeArgs += "-DGGML_CPU_ALL_VARIANTS=OFF" }
if ($env:BENTO_LLAMA_EXTRA_CMAKE_ARGS) { $CmakeArgs += ($env:BENTO_LLAMA_EXTRA_CMAKE_ARGS -split "\s+" | Where-Object { $_ }) }

$Sha = [System.Security.Cryptography.SHA256]::Create()
$FingerprintText = (@($LlamaCppTag, $LlamaCppSourceSha256, $Target) + $CmakeArgs) -join "`n"
$Fingerprint = -join ($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($FingerprintText)) | ForEach-Object { $_.ToString("x2") })

function Test-UpToDate {
  $info = Join-Path $Out "bento-llama-server.json"
  $sums = Join-Path $Out "SHA256SUMS"
  if (-not ((Test-Path $info) -and (Test-Path (Join-Path $Out "llama-server.exe")) -and (Test-Path $sums))) { return $false }
  if ((Get-Content -Raw $info) -notmatch [regex]::Escape("""fingerprint"": ""$Fingerprint""")) { return $false }
  foreach ($line in Get-Content $sums) {
    $digest, $name = $line -split "  ", 2
    $file = Join-Path $Out $name
    if (-not (Test-Path $file) -or (Get-Sha256 $file) -ne $digest) { return $false }
  }
  return $true
}

if (-not $Force -and (Test-UpToDate)) {
  Say "$Out is up to date (llama.cpp $LlamaCppTag, $Target)"
  Write-Output $Out
  exit 0
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { Fail "cmake is required (3.21 or later)" }

# ------------------------------------------------------------------------------------------ source

New-Item -ItemType Directory -Force -Path $Cache | Out-Null
if (-not $SourceTarball) {
  $SourceTarball = Join-Path $Cache "llama.cpp-$LlamaCppTag.tar.gz"
  if (-not (Test-Path $SourceTarball) -or (Get-Sha256 $SourceTarball) -ne $LlamaCppSourceSha256) {
    Say "downloading $LlamaCppSourceUrl"
    $part = "$SourceTarball.part"
    if (Test-Path $part) { Remove-Item -Force $part }
    Invoke-WebRequest -UseBasicParsing -Uri $LlamaCppSourceUrl -OutFile $part
    Move-Item -Force $part $SourceTarball
  }
}
if (-not (Test-Path $SourceTarball)) { Fail "source tarball not found: $SourceTarball" }
$Actual = Get-Sha256 $SourceTarball
if ($Actual -ne $LlamaCppSourceSha256) {
  if ($SourceTarball.StartsWith($Cache)) { Remove-Item -Force $SourceTarball }
  Fail "source digest mismatch for ${SourceTarball}: expected $LlamaCppSourceSha256, got $Actual"
}
Say "source verified: sha256 $Actual"

$Work = Join-Path $Cache "$LlamaCppTag-$Target"
$Src = Join-Path $Work "src"
$Build = Join-Path $Work "build"
if (Test-Path $Src) { Remove-Item -Recurse -Force $Src }
New-Item -ItemType Directory -Force -Path $Src, $Build | Out-Null
& tar.exe -xzf $SourceTarball -C $Src --strip-components=1
if ($LASTEXITCODE -ne 0) { Fail "could not extract $SourceTarball" }
if (-not (Test-Path (Join-Path $Src "CMakeLists.txt"))) { Fail "unexpected source layout in $SourceTarball" }

# ------------------------------------------------------------------------------------------ build

$Generator = @()
if (Get-Command ninja -ErrorAction SilentlyContinue) { $Generator = @("-G", "Ninja") }
elseif ($Target -eq "win32-arm64") { $Generator = @("-A", "ARM64") }
else { $Generator = @("-A", "x64") }
$Toolchain = @()
$Arch = $Target.Substring(6)
if (Get-Command clang -ErrorAction SilentlyContinue) {
  $Toolchain = @("-DCMAKE_TOOLCHAIN_FILE=$(Join-Path $Src "cmake\$Arch-windows-llvm.cmake")")
} elseif ($Target -eq "win32-arm64") {
  Fail "win32-arm64 needs LLVM clang on PATH (cmake/arm64-windows-llvm.cmake), as in the official release"
}

Say "configuring llama.cpp $LlamaCppTag for $Target"
& cmake -S $Src -B $Build @Generator @Toolchain @CmakeArgs
if ($LASTEXITCODE -ne 0) { Fail "cmake configure failed" }
& cmake --build $Build --config Release --target llama-server -j $Jobs
if ($LASTEXITCODE -ne 0) { Fail "cmake build failed" }
$Bin = Join-Path $Build "bin\Release"
if (-not (Test-Path (Join-Path $Bin "llama-server.exe"))) { $Bin = Join-Path $Build "bin" }
if (-not (Test-Path (Join-Path $Bin "llama-server.exe"))) { Fail "the build did not produce llama-server.exe" }

# ------------------------------------------------------------------------------------------ stage

if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
$Licenses = Join-Path $Out "licenses"
New-Item -ItemType Directory -Force -Path $Licenses | Out-Null
Copy-Item (Join-Path $Bin "llama-server.exe") $Out
Get-ChildItem -LiteralPath $Bin -Filter "*.dll" -File | ForEach-Object { Copy-Item $_.FullName $Out }

$LicenseFiles = [ordered]@{
  "LICENSE" = "LICENSE-llama.cpp"
  "vendor\cpp-httplib\LICENSE" = "LICENSE-cpp-httplib"
  "licenses\LICENSE-jsonhpp" = "LICENSE-nlohmann-json"
  "vendor\hash\xxhash\LICENSE" = "LICENSE-xxhash"
  "vendor\hash\rotate-bits\LICENSE.md" = "LICENSE-rotate-bits"
  "vendor\hash\sha256\LICENSE" = "LICENSE-sha256"
}
foreach ($entry in $LicenseFiles.GetEnumerator()) {
  $source = Join-Path $Src $entry.Key
  if (Test-Path $source) { Copy-Item $source (Join-Path $Licenses $entry.Value) } else { Say "warning: license file $($entry.Key) not found at $LlamaCppTag" }
}
$Utf8 = New-Object Text.UTF8Encoding $false
[IO.File]::WriteAllText((Join-Path $Licenses "THIRD-PARTY.txt"), ((Get-Licenses) -join "`n") + "`n", $Utf8)

$Info = [ordered]@{
  schema_version = 1
  name = "llama-server"
  tag = $LlamaCppTag
  build_number = [int]$LlamaCppBuildNumber
  commit = $LlamaCppCommit
  source_url = $LlamaCppSourceUrl
  source_sha256 = $LlamaCppSourceSha256
  license = "MIT"
  target = $Target
  executable = "llama-server.exe"
  cmake_args = $CmakeArgs
  fingerprint = $Fingerprint
}
# Plain "key": "value" spacing (the up-to-date check greps it) and no BOM (Node's JSON.parse rejects one).
$Json = ($Info | ConvertTo-Json -Depth 3) -replace '":\s+', '": '
[IO.File]::WriteAllText((Join-Path $Out "bento-llama-server.json"), $Json + "`n", $Utf8)

$Prefix = (Resolve-Path $Out).Path.TrimEnd("\") + "\"
$Lines = Get-ChildItem -LiteralPath $Out -Recurse -File |
  Where-Object { $_.Name -ne "SHA256SUMS" } |
  ForEach-Object { $_.FullName.Substring($Prefix.Length).Replace("\", "/") } |
  Sort-Object -CaseSensitive |
  ForEach-Object { "$(Get-Sha256 (Join-Path $Out $_))  $_" }
# LF line endings and no BOM, the same format as sha256sum and apps/desktop/scripts/checksums.mjs.
[IO.File]::WriteAllText((Join-Path $Out "SHA256SUMS"), (($Lines -join "`n") + "`n"), $Utf8)

# Start-Process: redirecting a native command's stderr in Windows PowerShell 5.1 turns it into errors.
$Probe = Start-Process -FilePath (Join-Path $Out "llama-server.exe") -ArgumentList "--version" -NoNewWindow -Wait -PassThru `
  -RedirectStandardOutput (Join-Path $Work "version.out") -RedirectStandardError (Join-Path $Work "version.err")
if ($Probe.ExitCode -ne 0) { Fail "llama-server.exe --version failed" }
Say "built llama-server $LlamaCppTag for ${Target}:"
Get-Licenses | ForEach-Object { Say $_ }
Write-Output $Out
