# Letterboxd Cinema installer (Windows, PowerShell). Run from the repo folder:  .\scripts\install.ps1
# Asks a few questions, writes .env, pre-seeds each service's config so nothing needs setting up by hand, and starts the stack.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Ask($prompt, $default) {
  $v = Read-Host "$prompt$(if ($default) { " [$default]" })"
  if ([string]::IsNullOrWhiteSpace($v)) { $default } else { $v.Trim() }
}
function NewKey { -join ((1..32) | ForEach-Object { '0123456789abcdef'[(Get-Random -Maximum 16)] }) }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Docker Desktop is not installed (or not on PATH). Install it from docker.com, then re-run."; exit 1 }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Write-Host "Docker Desktop is installed but not running. Start it, wait for the whale to settle, then re-run."; exit 1 }
if (Test-Path .env) { Write-Host ".env already exists — delete it to start over, or edit it directly."; exit 1 }

Write-Host ""
Write-Host "  Letterboxd Cinema — setup" -ForegroundColor White
Write-Host ""
$media  = (Ask "Folder for films and downloads (will get movies\ and downloads\ inside)" "D:\Media") -replace '\\','/'
$config = (Ask "Folder for app settings and databases" "D:\Cinema\config") -replace '\\','/'
if ($media -eq $config) { $config = "$media/.config"; Write-Host "  (settings will go in $config so they stay out of the way of the films)" }
do { $tz = Ask "Timezone (Region/City, e.g. Europe/London)" "Europe/London"; if ($tz -notmatch '/') { Write-Host "  That's not a timezone name — it looks like 'Europe/London' or 'America/New_York'." } } until ($tz -match '/')
$mode   = Ask "Access: 'lan' (this network only) or 'public' (your own domain, HTTPS)" "lan"
$site = ':80'; $cf = ''
if ($mode -eq 'public') {
  $site = Ask "Hostname (must point at this connection's public IP; Cloudflare DNS)" "films.example.com"
  $cf   = Ask "Cloudflare API token with 'Edit zone DNS' for that domain" ""
}
$gpu = Ask "GPU for transcoding: 'nvidia' or 'none'" "none"
$httpPort = Ask "Web port (80 unless something else is using it)" "80"
if ($httpPort -eq '80') { $httpsPort = '443'; $discPort = '7359'; $peerPort = '51413' }
else { $httpsPort = Ask "HTTPS port" "8443"; $discPort = Ask "Jellyfin discovery port (UDP)" "7360"; $peerPort = Ask "Torrent peer port" "51414" }

$radarrKey = NewKey; $prowlarrKey = NewKey

# ---- folders
foreach ($d in "$media/movies", "$media/downloads/complete", "$media/downloads/incomplete",
               "$config/radarr", "$config/prowlarr", "$config/transmission", "$config/jellyfin/config", "$config/jellyfin-cache",
               "$config/helper", "$config/caddy/data", "$config/caddy/config") { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# ---- pre-seeded configs (only written if absent, so re-running never clobbers a live install)
$arr = @"
<Config>
  <ApiKey>{0}</ApiKey>
  <AuthenticationMethod>Forms</AuthenticationMethod>
  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>
  <BindAddress>*</BindAddress>
  <Port>{1}</Port>
  <UrlBase></UrlBase>
  <AnalyticsEnabled>False</AnalyticsEnabled>
</Config>
"@
if (-not (Test-Path "$config/radarr/config.xml"))   { ($arr -f $radarrKey, 7878)   | Set-Content -NoNewline "$config/radarr/config.xml" }
if (-not (Test-Path "$config/prowlarr/config.xml")) { ($arr -f $prowlarrKey, 9696) | Set-Content -NoNewline "$config/prowlarr/config.xml" }
if (-not (Test-Path "$config/transmission/settings.json")) { Copy-Item config/transmission-settings.json "$config/transmission/settings.json" }
if ($gpu -eq 'nvidia' -and -not (Test-Path "$config/jellyfin/config/encoding.xml")) { Copy-Item config/jellyfin-encoding-nvenc.xml "$config/jellyfin/config/encoding.xml" }

# ---- .env
$env = @(
  "APP_NAME=Cinema", "MEDIA_PATH=$media", "CONFIG_PATH=$config", "TZ=$tz", "PUID=1000", "PGID=1000",
  "SITE_ADDRESS=$site", "RADARR_API_KEY=$radarrKey", "PROWLARR_API_KEY=$prowlarrKey",
  "HTTP_PORT=$httpPort", "HTTPS_PORT=$httpsPort", "PEER_PORT=$peerPort", "DISCOVERY_PORT=$discPort", "MAX_MB_PER_MINUTE=150", "SEED_RATIO=1.0"
)
if ($mode -eq 'public') { $env += "COMPOSE_PROFILES=public"; $env += "CLOUDFLARE_API_TOKEN=$cf" }
if ($gpu -eq 'nvidia')  { $env += "COMPOSE_FILE=docker-compose.yml:docker-compose.nvidia.yml" }
$env -join "`n" | Set-Content -NoNewline .env

Write-Host ""
Write-Host "Starting…" -ForegroundColor White
docker compose up -d --build
Write-Host ""
if ($mode -eq 'public') { Write-Host "Done. Forward TCP 80 and 443 on your router to this PC, then open https://$site" }
else { Write-Host "Done. Open http://localhost$(if ($httpPort -ne '80') { ":$httpPort" }) (or this PC's IP from another device on your network)." }
Write-Host "Your first visit walks you through naming the cinema and creating your account."
