# Bootstrap dotfiles on Windows.
# Run from an elevated PowerShell prompt:
#
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\bootstrap\install.ps1
#
# Or from the web (replace YOUR_USERNAME):
#   Set-ExecutionPolicy Bypass -Scope Process -Force; `
#   Invoke-Expression ((New-Object System.Net.WebClient).DownloadString( `
#     'https://raw.githubusercontent.com/YOUR_USERNAME/dotfiles/main/bootstrap/install.ps1'))

param(
    [string]$DotfilesRepo = "https://github.com/nickvigilante/dotfiles.git"
)

$ErrorActionPreference = "Stop"

function Write-Header { param($Msg) Write-Host "`n$Msg" -ForegroundColor Cyan }
function Write-Info   { param($Msg) Write-Host "  -> $Msg" }
function Write-OK     { param($Msg) Write-Host "  OK $Msg" -ForegroundColor Green }

Write-Header "Dotfiles Bootstrap (Windows)"
Write-Info "Repo: $DotfilesRepo"

# ── Chocolatey ────────────────────────────────────────────────────────────────
Write-Header "Step 1/3 - Chocolatey"
if (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-OK "Chocolatey already installed."
} else {
    Write-Info "Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = `
        [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString(
        'https://community.chocolatey.org/install.ps1'))
    Write-OK "Chocolatey installed."
}

# ── chezmoi ───────────────────────────────────────────────────────────────────
Write-Header "Step 2/3 - chezmoi"
if (Get-Command chezmoi -ErrorAction SilentlyContinue) {
    Write-OK "chezmoi already installed."
} else {
    Write-Info "Installing chezmoi via Chocolatey..."
    choco install chezmoi -y
    Write-OK "chezmoi installed."
}

# ── Apply dotfiles ─────────────────────────────────────────────────────────────
Write-Header "Step 3/3 - Apply dotfiles"
Write-Info "You'll be prompted for: profile, name, email, machine role."
Write-Host ""

chezmoi init --apply $DotfilesRepo

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Header "Done!"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  1. Open a Cygwin terminal"
Write-Host "  2. Run: exec zsh"
Write-Host "  3. Check status: chezmoi status"
Write-Host ""
