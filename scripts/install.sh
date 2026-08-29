#!/usr/bin/env bash
# Letterboxd Cinema installer (Linux / macOS). Run from the repo folder:  ./scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ask() { local v; read -r -p "$1${2:+ [$2]}: " v; echo "${v:-$2}"; }
newkey() { head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

command -v docker >/dev/null || { echo "Docker is not installed. Install Docker (Engine or Desktop), then re-run."; exit 1; }
[ -f .env ] && { echo ".env already exists — delete it to start over, or edit it directly."; exit 1; }

echo; echo "  Letterboxd Cinema — setup"; echo
name=$(ask "Name for your cinema (shown as the wordmark)" "Cinema")
media=$(ask "Folder for films and downloads (will get movies/ and downloads/ inside)" "$HOME/media")
config=$(ask "Folder for app settings and databases" "$HOME/cinema/config")
tz=$(ask "Timezone" "$( (readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||') || echo Europe/London)")
mode=$(ask "Access: 'lan' (this network only) or 'public' (your own domain, HTTPS)" "lan")
site=":80"; cf=""
if [ "$mode" = public ]; then
  site=$(ask "Hostname (must point at this connection's public IP; Cloudflare DNS)" "films.example.com")
  cf=$(ask "Cloudflare API token with 'Edit zone DNS' for that domain" "")
fi
gpu=$(ask "GPU for transcoding: 'nvidia' or 'none'" "none")
radarr_key=$(newkey); prowlarr_key=$(newkey)

mkdir -p "$media"/{movies,downloads/complete,downloads/incomplete} \
         "$config"/{radarr,prowlarr,transmission,jellyfin/config,jellyfin-cache,helper,caddy/data,caddy/config}

arr() { printf '<Config>\n  <ApiKey>%s</ApiKey>\n  <AuthenticationMethod>Forms</AuthenticationMethod>\n  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>\n  <BindAddress>*</BindAddress>\n  <Port>%s</Port>\n  <UrlBase></UrlBase>\n  <AnalyticsEnabled>False</AnalyticsEnabled>\n</Config>\n' "$1" "$2"; }
[ -f "$config/radarr/config.xml" ]   || arr "$radarr_key" 7878   > "$config/radarr/config.xml"
[ -f "$config/prowlarr/config.xml" ] || arr "$prowlarr_key" 9696 > "$config/prowlarr/config.xml"
[ -f "$config/transmission/settings.json" ] || cp config/transmission-settings.json "$config/transmission/settings.json"
if [ "$gpu" = nvidia ] && [ ! -f "$config/jellyfin/config/encoding.xml" ]; then cp config/jellyfin-encoding-nvenc.xml "$config/jellyfin/config/encoding.xml"; fi

{
  echo "APP_NAME=$name"; echo "MEDIA_PATH=$media"; echo "CONFIG_PATH=$config"; echo "TZ=$tz"
  echo "PUID=$(id -u)"; echo "PGID=$(id -g)"; echo "SITE_ADDRESS=$site"
  echo "RADARR_API_KEY=$radarr_key"; echo "PROWLARR_API_KEY=$prowlarr_key"
  [ "$mode" = public ] && { echo "COMPOSE_PROFILES=public"; echo "CLOUDFLARE_API_TOKEN=$cf"; }
  [ "$gpu" = nvidia ] && echo "COMPOSE_FILE=docker-compose.yml:docker-compose.nvidia.yml"
} > .env

echo; echo "Starting…"
docker compose up -d --build
echo
if [ "$mode" = public ]; then echo "Done. Forward TCP 80 and 443 on your router to this machine, then open https://$site"
else echo "Done. Open http://localhost (or http://<this machine's IP> from another device on your network)."; fi
echo "First visit: sign in with the Jellyfin admin account you create at http://localhost:8096 (one-time wizard)."
