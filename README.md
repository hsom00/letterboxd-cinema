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
./scripts/install.sh         # macOS / Linux
```

The installer asks six questions (name, folders, timezone, LAN or public, GPU), writes `.env`, pre-seeds every service's settings, and starts the stack. First start pulls the images and takes a few minutes.

Then, once only:

1. Open `http://localhost/web/` and complete Jellyfin's short wizard: create your admin account and add a **Movies** library pointing at `/data/movies`.
2. Open `http://localhost` and sign in with that account. That's your cinema.

Adding films: in Radarr (`http://localhost:7878`) → Settings → Import Lists → Custom List, with a URL like `http://letterboxd-list:5000/<your-letterboxd-user>/watchlist/`. Anything you add on Letterboxd turns up in the cinema. Radarr, Prowlarr and Transmission are only reachable from the machine itself; the cinema is what you share.

> Steps 1 and the import-list setup are exactly what the upcoming provisioner and onboarding flow will do for you. They're on the roadmap below.

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
config/                     pre-seeded settings the installer copies into place
scripts/                    installers
```

`MEDIA_PATH` gets `movies/` and `downloads/`. Every container sees it as `/data`, so Radarr moves finished downloads into the library with a hard link rather than a copy, and Jellyfin reads the same folder read-only.

## Keyboard

`R` random film · `G` toggle reel/grid · `Esc` close · in the player: `Space`, `←` `→` ±10s, `F` fullscreen, `M` mute.

## Roadmap

- **Provisioner**: a one-shot container that configures Radarr, Prowlarr, Transmission and Jellyfin over their APIs on first start (download client, root folder, quality caps, seed limits, Jellyfin admin + library, backdrop limit), so the "once only" steps above disappear.
- **Onboarding**: a first-run wizard in the cinema's own design — name, admin account, Letterboxd username — replacing Jellyfin's.
- Intel / AMD transcoding overlays; pinned image versions and a release cadence.

## Licence

MIT.
