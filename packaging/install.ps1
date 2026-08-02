# Install the AI Shell desktop app on Windows.
#
#     irm https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.ps1 | iex
#
# It downloads the latest release installer and runs it silently. That installer
# is per-user, so nothing here needs an administrator and nothing lands outside
# your own profile.
#
# Two knobs, both optional - set them before piping to iex:
#
#     $env:AI_SHELL_VERSION = "0.1.0"   install a specific release
#     $env:AI_SHELL_PORTABLE = "1"      unpack the zip instead of running the
#                                       installer: no Start Menu entry, no
#                                       uninstall entry, just a folder
#
# What this does NOT download is the model - several gigabytes that the app
# fetches into %APPDATA%\ai-shell the first time you run it, so that
# reinstalling the app doesn't mean downloading the weights again.

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "Vuwar/nl-shell"
$api = "https://api.github.com/repos/$repo/releases"
# Any non-empty value except "0" counts as on. A bare cast wouldn't: every
# non-empty string is $true in PowerShell, so AI_SHELL_PORTABLE=0 would turn
# the thing on.
$portable = $env:AI_SHELL_PORTABLE -and $env:AI_SHELL_PORTABLE -ne "0"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "AI Shell is built for 64-bit Windows only."
}

# TLS 1.2 isn't the default in Windows PowerShell 5.1, and github.com won't
# negotiate anything older.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$releaseUrl = if ($env:AI_SHELL_VERSION) { "$api/tags/v$($env:AI_SHELL_VERSION)" } else { "$api/latest" }

Write-Host "Looking up the release..."
try {
    $release = Invoke-RestMethod -Uri $releaseUrl -Headers @{ "User-Agent" = "ai-shell-installer" }
} catch {
    throw "Couldn't reach the releases page for ${repo}: $($_.Exception.Message)"
}

$suffix = if ($portable) { "windows-x64.zip" } else { "windows-x64-setup.exe" }
$asset = $release.assets | Where-Object { $_.name -like "*$suffix" } | Select-Object -First 1
if (-not $asset) {
    throw "Release $($release.tag_name) has no *$suffix build. See https://github.com/$repo/releases"
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ai-shell-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $download = Join-Path $tmp $asset.name
    Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
    # Invoke-WebRequest's progress bar makes the download several times slower
    # in 5.1 - it repaints the console on every chunk.
    $previous = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $download -UseBasicParsing
    } finally {
        $ProgressPreference = $previous
    }

    if ($portable) {
        $target = Join-Path $env:LOCALAPPDATA "Programs\AI Shell"
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Write-Host "Unpacking to $target..."
        # The zip contains an "AI Shell" folder, so expand into the parent.
        Expand-Archive -Path $download -DestinationPath (Split-Path $target -Parent) -Force
        Write-Host ""
        Write-Host "Installed to $target"
        Write-Host "Run it with: & '$target\AI Shell.exe'"
    } else {
        Write-Host "Running the installer..."
        # /SILENT rather than /VERYSILENT so there's a progress window: this was
        # started by a one-liner, and a several-second pause with nothing on
        # screen reads as a hang. Both suppress every prompt.
        $process = Start-Process -FilePath $download -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "The installer exited with code $($process.ExitCode)."
        }
        Write-Host ""
        Write-Host "Installed. Find 'AI Shell' in the Start Menu."
    }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "First run downloads the inference engine and a model (a few GB) into"
Write-Host "%APPDATA%\ai-shell. The window opens straight away and says what it's"
Write-Host "waiting for."
