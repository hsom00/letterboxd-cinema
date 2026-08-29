# Letterboxd Cinema

A self-hosted film library that feels like a cinema, not a spreadsheet.

Full-bleed stills, serif titles, one film at a time. Letterboxd ratings as plain white stars. A "pick one for me" button. Filter by country. Films arrive on their own from your Letterboxd lists, get picked up by Jellyfin, and play in the page with the lights dimmed. Everything runs in Docker on a machine in your house.

Under the hood it's Jellyfin, Radarr, Prowlarr and Transmission, pre-wired so you never have to open them, with a small front-end and helper on top. It is not affiliated with Letterboxd; it just loves it.

## What you need

- A computer that stays on (Windows, macOS or Linux) with [Docker](https://www.docker.com/) installed.
- Somewhere to keep films — a big disk or folder.
- Optionally: a domain on Cloudflare if you want to watch from outside the house, and an NVIDIA GPU if you want hardware transcoding.

## Install

```powershell
git clone https://github.com/hsom00/letterboxd-cinema
cd letterboxd-cinema
.\scripts\install.ps1        # Windows
bash scripts/install.sh      # macOS / Linux
```

The installer asks about the machine — folders, timezone, LAN or public, GPU, ports — writes `.env`, pre-seeds every service's settings, and starts the stack. First start pulls the images and takes a few minutes.

Then open `http://localhost`. Your first visit is a short onboarding in the cinema's own design: name it, create your account, give your Letterboxd username, choose where films may come from. On "Set up my cinema" everything is wired together over the services' APIs — Jellyfin account and Movies library, Radarr to Transmission with hard-linking and a size ceiling per quality, Prowlarr to Radarr, your watchlist as the shopping list — and you sign in. Nothing else to configure; the projection booth (Radarr, Prowlarr, Transmission at `localhost:7878`, `:9696`, `:9091`) is there if you ever want it, reachable only from the machine itself.

Anything you add to your Letterboxd watchlist turns up in the cinema.

## Remote access

Choose `public` in the installer, give it a hostname you own on Cloudflare and an API token with *Edit zone DNS* for that zone. Forward TCP 80 and 443 (and UDP 443 if you can) on your router to the machine. Caddy fetches and renews the HTTPS certificate; a small container keeps the DNS record pointed at your home IP when it changes. Only the cinema is published — never Radarr, Prowlarr or Transmission.

Prefer not to open ports? Stay on `lan` and use [Tailscale](https://tailscale.com) on the server and your laptop.

## Layout

```
docker-compose.yml          the stack; every path and name comes from .env
docker-compose.nvidia.yml   overlay: NVIDIA transcoding for Jellyfin
caddy/Caddyfile             routing: / and /app/* are the cinema, everything else Jellyfin
web/                        the front-end (plain HTML/CSS/JS, no build step)
helper/                     tiny Python service: Letterboxd ratings & countries, app config, admin actions
provision/                  one-shot container that configures Radarr, Prowlarr and Jellyfin over their APIs
config/                     pre-seeded settings the installer copies into place
scripts/                    installers
```

`MEDIA_PATH` gets `movies/` and `downloads/`. Every container sees it as `/data`, so Radarr moves finished downloads into the library with a hard link rather than a copy, and Jellyfin reads the same folder read-only.

## Keyboard

`R` random film · `G` toggle reel/grid · `Esc` close · in the player: `Space`, `←` `→` ±10s, `F` fullscreen, `M` mute.

## Roadmap

- **Installer, properly.** The two shell scripts are a stopgap and have already bitten twice. Replace them with one cross-platform installer (Python, or a tiny Go binary) that: checks Docker is running and ports 80/443 are free before asking anything, expands `~`, validates paths and timezone, warns about disk space, can be re-run safely, supports a non-interactive mode for scripted installs, and prints a clear "what next" at the end. Consider moving the machine questions into the browser too, leaving the installer with nothing to ask.

- Intel / AMD transcoding overlays; pinned image versions and a release cadence.

## Licence

MIT.
