#!/usr/bin/env bash
# Letterboxd Cinema installer (Linux / macOS). Run from the repo folder:  bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ask() { local v; read -r -p "$1${2:+ [$2]}: " v; echo "${v:-$2}"; }
newkey() { head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

command -v docker >/dev/null || { echo "Docker is not installed. Install Docker (Engine or Desktop), then re-run."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start Docker Desktop (or the docker service), wait for it to settle, then re-run."; exit 1; }
if [ -f .env ]; then
  echo "A .env from a previous run exists. Continuing will rewrite it (folders and settings already on disk are kept)."
  read -r -p "Press Enter to continue, or Ctrl-C to stop: " _
fi

echo; echo "  Letterboxd Cinema — setup"; echo
media=$(ask "Folder for films and downloads (will get movies/ and downloads/ inside)" "$HOME/media")
config=$(ask "Folder for app settings and databases" "$HOME/cinema/config")
media="${media/#\~/$HOME}"; config="${config/#\~/$HOME}"
[ "$media" = "$config" ] && { config="$media/.config"; echo "  (settings will go in $config so they stay out of the way of the films)"; }
default_tz=$( (readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||') || true ); default_tz=${default_tz:-Europe/London}
while :; do
  tz=$(ask "Timezone (Region/City, e.g. Europe/London)" "$default_tz")
  case "$tz" in */*) break ;; *) echo "  That's not a timezone name — it looks like 'Europe/London' or 'America/New_York'." ;; esac
done
mode=$(ask "Access: 'lan' (this network only) or 'public' (your own domain, HTTPS)" "lan")
site=":80"; cf=""
if [ "$mode" = public ]; then
  site=$(ask "Hostname (must point at this connection's public IP; Cloudflare DNS)" "films.example.com")
  cf=$(ask "Cloudflare API token with 'Edit zone DNS' for that domain" "")
fi
gpu=$(ask "GPU for transcoding: 'nvidia' or 'none'" "none")
http_port=$(ask "Web port (80 unless something else is using it)" "80")
if [ "$http_port" = 80 ]; then https_port=443; disc_port=7359; peer_port=51413
else https_port=$(ask "HTTPS port" "8443"); disc_port=$(ask "Jellyfin discovery port (UDP)" "7360"); peer_port=$(ask "Torrent peer port" "51414"); fi
# reuse keys already baked into an existing install, otherwise generate
existing_key() { [ -f "$1" ] && sed -n 's|.*<ApiKey>\([^<]*\)</ApiKey>.*|\1|p' "$1" | head -1; }
radarr_key=$(existing_key "$config/radarr/config.xml"); radarr_key=${radarr_key:-$(newkey)}
prowlarr_key=$(existing_key "$config/prowlarr/config.xml"); prowlarr_key=${prowlarr_key:-$(newkey)}

mkdir -p "$media"/{movies,downloads/complete,downloads/incomplete} \
         "$config"/{radarr,prowlarr,transmission,jellyfin/config,jellyfin-cache,helper,caddy/data,caddy/config}

arr() { printf '<Config>\n  <ApiKey>%s</ApiKey>\n  <AuthenticationMethod>Forms</AuthenticationMethod>\n  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>\n  <BindAddress>*</BindAddress>\n  <Port>%s</Port>\n  <UrlBase></UrlBase>\n  <AnalyticsEnabled>False</AnalyticsEnabled>\n</Config>\n' "$1" "$2"; }
[ -f "$config/radarr/config.xml" ]   || arr "$radarr_key" 7878   > "$config/radarr/config.xml"
[ -f "$config/prowlarr/config.xml" ] || arr "$prowlarr_key" 9696 > "$config/prowlarr/config.xml"
[ -f "$config/transmission/settings.json" ] || cp config/transmission-settings.json "$config/transmission/settings.json"
if [ "$gpu" = nvidia ] && [ ! -f "$config/jellyfin/config/encoding.xml" ]; then cp config/jellyfin-encoding-nvenc.xml "$config/jellyfin/config/encoding.xml"; fi

{
  echo "APP_NAME=Cinema"; echo "MEDIA_PATH=$media"; echo "CONFIG_PATH=$config"; echo "TZ=$tz"
  echo "PUID=$(id -u)"; echo "PGID=$(id -g)"; echo "SITE_ADDRESS=$site"
  echo "RADARR_API_KEY=$radarr_key"; echo "PROWLARR_API_KEY=$prowlarr_key"
  echo "HTTP_PORT=$http_port"; echo "HTTPS_PORT=$https_port"; echo "PEER_PORT=$peer_port"; echo "DISCOVERY_PORT=$disc_port"
  echo "MAX_MB_PER_MINUTE=150"; echo "SEED_RATIO=1.0"
  if [ "$mode" = public ]; then echo "COMPOSE_PROFILES=public"; echo "CLOUDFLARE_API_TOKEN=$cf"; fi
  if [ "$gpu" = nvidia ]; then echo "COMPOSE_FILE=docker-compose.yml:docker-compose.nvidia.yml"; fi
} > .env

echo; echo "Starting…"
docker compose up -d --build
echo
if [ "$mode" = public ]; then echo "Done. Forward TCP 80 and 443 on your router to this machine, then open https://$site"
else echo "Done. Open http://localhost${http_port:+$( [ "$http_port" != 80 ] && echo ":$http_port")} (or this machine's IP from another device on your network)."; fi
echo "Your first visit walks you through naming the cinema and creating your account."
