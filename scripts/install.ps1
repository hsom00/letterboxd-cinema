# Letterboxd Cinema installer (Windows, PowerShell). Run from the repo folder:  .\scripts\install.ps1
# Asks a few questions, writes .env, pre-seeds each service's config so nothing needs setting up by hand, and starts the stack.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Ask($prompt, $default) {
  $suffix = ''
  if ($default) { $suffix = ' [' + $default + ']' }
  $v = Read-Host ($prompt + $suffix)
  if ([string]::IsNullOrWhiteSpace($v)) { return $default }
  return $v.Trim()
}
function NewKey { -join ((1..32) | ForEach-Object { '0123456789abcdef'[(Get-Random -Maximum 16)] }) }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Docker Desktop is not installed (or not on PATH). Install it from docker.com, then re-run."; exit 1 }
if (Test-Path .env) { Write-Host ".env already exists — delete it to start over, or edit it directly."; exit 1 }

Write-Host ""
Write-Host "  Letterboxd Cinema — setup" -ForegroundColor White
Write-Host ""
$media  = (Ask "Folder for films and downloads (will get movies\ and downloads\ inside)" "D:\Media") -replace '\\','/'
$config = (Ask "Folder for app settings and databases" (Join-Path (Get-Location).Path 'appdata')) -replace '\\','/'
$tz     = Ask "Timezone" ((Get-TimeZone).Id -replace ' ', '_' | ForEach-Object { if ($_ -match '^[A-Za-z]+/[A-Za-z_]+$') { $_ } else { 'Europe/London' } })
$mode   = Ask "Access: 'lan' (this network only) or 'public' (your own domain, HTTPS)" "lan"
$site = ':80'; $cf = ''
if ($mode -eq 'public') {
  $site = Ask "Hostname (must point at this connection's public IP; Cloudflare DNS)" "films.example.com"
  $cf   = Ask "Cloudflare API token with 'Edit zone DNS' for that domain" ""
}
$gpu = Ask "GPU for transcoding: 'nvidia' or 'none'" "none"
$httpPort = Ask "Web port (80 unless something else is using it)" "80"
$httpsPort = if ($httpPort -eq '80') { '443' } else { Ask "HTTPS port" "8443" }
$peerPort = Ask "Torrent peer port" "51413"
$discPort = if ($httpPort -eq '80') { '7359' } else { Ask "Jellyfin discovery port (UDP)" "7360" }

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
$lines = @(
  "APP_NAME=Cinema", "MEDIA_PATH=$media", "CONFIG_PATH=$config", "TZ=$tz", "PUID=1000", "PGID=1000",
  "SITE_ADDRESS=$site", "RADARR_API_KEY=$radarrKey", "PROWLARR_API_KEY=$prowlarrKey",
  "HTTP_PORT=$httpPort", "HTTPS_PORT=$httpsPort", "PEER_PORT=$peerPort", "DISCOVERY_PORT=$discPort", "MAX_MB_PER_MINUTE=150", "SEED_RATIO=1.0"
)
if ($mode -eq 'public') { $lines += "COMPOSE_PROFILES=public"; $lines += "CLOUDFLARE_API_TOKEN=$cf" }
if ($gpu -eq 'nvidia')  { $lines += "COMPOSE_FILE=docker-compose.yml:docker-compose.nvidia.yml" }
[IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), ($lines -join "`n"))

Write-Host ""
Write-Host "Starting…" -ForegroundColor White
docker compose up -d
Write-Host ""
if ($mode -eq 'public') { Write-Host "Done. Forward TCP 80 and 443 on your router to this PC, then open https://$site" }
else { $u = 'http://localhost'; if ($httpPort -ne '80') { $u = $u + ':' + $httpPort }; Write-Host ('Done. Open ' + $u + " (or this PC's IP from another device on your network).") }
Write-Host "Your first visit walks you through naming the cinema and creating your account."
