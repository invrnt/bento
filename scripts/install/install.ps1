# Installs the standalone `bento` CLI for the current Windows user.
#
#   irm https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.ps1 | iex
#
# Environment:
#   BENTO_CLI_VERSION   version to install (e.g. 0.1.0); default: the latest Bento release (`vX.Y.Z`)
#   BENTO_CLI_BASE_URL  where the release assets live; default:
#                       https://github.com/invrnt/bento/releases/download/v<version>
#   BENTO_INSTALL_DIR   default: %LOCALAPPDATA%\Bento CLI
#
# The archive's SHA-256 is verified before anything is installed. No administrator rights needed.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repository = "invrnt/bento"

function Fail([string] $Message) {
  # `throw`, not `exit`: under `irm | iex` exit would close the person's PowerShell window.
  throw "bento install: $Message"
}

function Get-Download([string] $Url, [string] $Destination) {
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  "AMD64" { "x64" }
  "ARM64" { "x64" } # Windows on Arm runs the x64 build through emulation.
  default { Fail "unsupported processor $($env:PROCESSOR_ARCHITECTURE)" }
}

$work = Join-Path ([IO.Path]::GetTempPath()) ("bento-install-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  $version = $env:BENTO_CLI_VERSION
  $baseUrl = $env:BENTO_CLI_BASE_URL
  if ($baseUrl) {
    $baseUrl = $baseUrl.TrimEnd("/")
    if (-not $version) {
      $versionFile = Join-Path $work "VERSION"
      Get-Download "$baseUrl/VERSION" $versionFile
      $version = (Get-Content -Raw $versionFile).Trim()
    }
  } else {
    if (-not $version) {
      # releases/latest is the product release; Android releases are published with --latest=false.
      $latest = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repository/releases/latest"
      if ($latest.tag_name -notmatch '^v[0-9]') { Fail "no Bento release found; set BENTO_CLI_VERSION" }
      $version = $latest.tag_name.Substring(1)
    }
    $baseUrl = "https://github.com/$Repository/releases/download/v$($version.TrimStart('v'))"
  }
  $version = $version.TrimStart("v")
  if ($version -notmatch '^[0-9A-Za-z.+-]+$') { Fail "invalid version '$version'" }

  $asset = "bento-cli-$version-windows-$arch.zip"
  Write-Host "Downloading Bento CLI $version (windows-$arch)..."
  $archive = Join-Path $work $asset
  $sums = Join-Path $work "SHA256SUMS"
  Get-Download "$baseUrl/$asset" $archive
  Get-Download "$baseUrl/SHA256SUMS" $sums

  $expected = $null
  foreach ($line in Get-Content $sums) {
    $parts = $line -split '\s+', 2
    if ($parts.Count -eq 2 -and $parts[1].TrimStart("*") -eq $asset) { $expected = $parts[0].ToLowerInvariant(); break }
  }
  if (-not $expected) { Fail "$asset is not listed in SHA256SUMS" }
  $actual = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLowerInvariant()
  if ($expected -ne $actual) { Fail "checksum mismatch for $asset; nothing was installed" }

  $extract = Join-Path $work "extract"
  Expand-Archive -Path $archive -DestinationPath $extract
  if (-not (Test-Path (Join-Path $extract "bento\bento.exe"))) { Fail "unexpected archive layout (bento\bento.exe missing)" }

  $installDir = if ($env:BENTO_INSTALL_DIR) { $env:BENTO_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "Bento CLI" }
  $appDir = Join-Path $installDir "app"
  New-Item -ItemType Directory -Force -Path $installDir | Out-Null
  if (Test-Path $appDir) { Remove-Item -Recurse -Force $appDir }
  Move-Item (Join-Path $extract "bento") $appDir

  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $entries = @($userPath -split ";" | Where-Object { $_ })
  if ($entries -notcontains $appDir) {
    [Environment]::SetEnvironmentVariable("Path", (($entries + $appDir) -join ";"), "User")
    Write-Host "Added $appDir to your PATH (open a new terminal to use it)."
  }
  $env:Path = "$appDir;$env:Path"

  Write-Host "Bento CLI $version installed: $appDir\bento.exe"
  Write-Host ""
  Write-Host "Next step:  bento setup"
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
