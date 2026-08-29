# Letterboxd Cinema

A private cinema in your home, fed by your Letterboxd watchlist. Add a film to a list, and the server does the rest.

With an interface built around film discovery rather than browsing, hopefully the experience is closer to walking past the posters outside a cinema than to searching a database.

This app is for those who love films and want to spend their evenings watching them, not managing them. Anyone with a little technical knowledge should be able to set it up by following the instructions below.

## How it works

You add something interesting to your Letterboxd watchlist. In the background, the server gets to work locating a copy of that film. When a good match appears, the server downloads and files it into the library, fetching the rating and country from Letterboxd. Stuck or dead downloads are dropped and searched again.

The film then appears in the cinema, with subtitles and audio tracks where the copy has them, and playback position synced across your devices. Everything updates itself weekly.

## Behind the scenes

Letterboxd Cinema is a Docker stack: a set of well-known open-source tools (Jellyfin, Radarr, Prowlarr, Transmission and a few others) installed and configured for you, with a bespoke user interface on top that exposes only the settings you need. The underlying tools are great, but each has its own settings, its own account and its own ideas about folders, and connecting them takes an evening of reading. The cinema does that once, on first start. The tools are still there if you ever want to open them. There are no folders to manage, no download client to check.

It works in any browser, at home or away. The Jellyfin apps on your TV and phone work with it too.

## What you need

- A computer that can stay switched on: a desktop PC, a Mac mini, an old laptop or a small home server. Windows, macOS or Linux.
- Space for films. A large drive, or a folder on one.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed on that computer. It is free, and the cinema runs inside it.
- Optional: your own web address (a domain on Cloudflare) if you want to watch from anywhere. You could also set it up via Tailscale.
- Optional: an NVIDIA graphics card, for smoother playback on phones and slow connections.

## Setting it up

1. **Get the code.** In a terminal (PowerShell on Windows, Terminal on Mac):
   ```
   git clone https://github.com/hsom00/letterboxd-cinema
   cd letterboxd-cinema
   ```
2. **Run the installer.** It asks where to keep films and settings, your timezone, whether the cinema is for home only or the whole internet, and whether you have an NVIDIA card. The defaults are fine.
   ```
   .\scripts\install.ps1        # Windows
   bash scripts/install.sh      # Mac / Linux
   ```
   The first start downloads everything it needs. Give it a few minutes.
3. **Open `http://localhost`** in a browser on that computer. It walks you through naming your cinema, creating your account, connecting your Letterboxd and choosing where films may come from. Then sign in.

That is all. Add something to your Letterboxd watchlist and check back in an hour.

## Everyday use

You rarely need to touch it. Films arrive from your watchlist and the system updates itself weekly.

Your initial in the top-right corner opens **Settings**. From there you can look for new films now, change your Letterboxd account, see what is downloading, switch sources on and off, and rename the cinema. Admins also get a quiet **Remove from library** link at the bottom of any film page.

To watch from outside the house, either choose *public* during setup (you need a domain on Cloudflare and to forward two ports on your router; the installer tells you which), or keep it home-only and run [Tailscale](https://tailscale.com) on the server and your laptop, which needs no router changes.

A word on responsibility: the cinema fetches films from public sources you choose. What you download, and whether you may, is between you and the law where you live.

## Technical info

For the curious and the technical. Everything below is optional reading.

The cinema is a thin, hand-made front-end over a stack of well-known open-source tools, wired together so you never have to open them: **Jellyfin** (media server and player back-end), **Radarr** (decides what to fetch and files it), **Prowlarr** (talks to the sources), **Transmission** (does the fetching), **Decluttarr** (clears stuck downloads and retries), **letterboxd-list-radarr** (turns a Letterboxd list into something Radarr understands), **Caddy** (serves the site and gets your HTTPS certificate) and **Watchtower** (keeps everything updated). Two small pieces are our own: a **helper** that fetches Letterboxd ratings and countries and handles admin actions, and a **provisioner** that configures all of the above over their APIs on first start.

```
docker-compose.yml          the stack; every path and name comes from .env
docker-compose.nvidia.yml   overlay: NVIDIA transcoding for Jellyfin
docker-compose.dev.yml      overlay: build the images locally and serve web/ from the folder
web/                        the front-end — plain HTML, CSS and JavaScript, no build step
helper/                     Python: Letterboxd lookups, /api/config, onboarding, admin actions
provision/                  Python: configures Radarr, Prowlarr and Jellyfin; runs on every start, idempotent
caddy/                      Caddyfile and the image that bakes web/ into Caddy
config/                     pre-seeded settings the installer copies into place
scripts/                    installers
appdata/                    (created by the installer, not in git) every service's settings and databases
```

**Paths.** `MEDIA_PATH` gets `movies/` and `downloads/`. Every container sees it as `/data`, so Radarr moves a finished download into the library with a hard link rather than a copy, and Jellyfin reads the same folder read-only. `CONFIG_PATH` (default `appdata/` inside the clone) holds each service's state.

**Ports.** Only the cinema is exposed (80/443). Radarr, Prowlarr, Transmission and Jellyfin are bound to `127.0.0.1`. They are reachable from the machine itself at `:7878`, `:9696`, `:9091` and `:8096`, and never from the network.

**Updates.** GitHub builds the three images (`web`, `helper`, `provision`) whenever the `stable` branch moves and publishes them to `ghcr.io/hsom00/letterboxd-cinema/`. Watchtower pulls them, and the third-party images, weekly. `CHANNEL=main` in `.env` follows every commit. A change to `docker-compose.yml` itself is the one thing that needs a hand: `git pull && docker compose up -d`.

**Developing.** Set `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` in `.env` and run `docker compose up -d --build`. The front-end is served straight from `web/`, so edits show on refresh. The installer sets `COMPOSE_PATH_SEPARATOR=:` so that line works on Windows too.

**Two installs on one machine** (a test next to a live one): use separate folders, separate `CONFIG_PATH` values, and different `HTTP_PORT`, `HTTPS_PORT`, `PEER_PORT` and `DISCOVERY_PORT` values.

**Keyboard.** `R` random · `G` reel/grid · `Esc` close · in the player: `Space` play/pause, `←` `→` ±10s, `F` fullscreen, `M` mute.

## Roadmap

- **A better installer.** One cross-platform installer that checks Docker and ports before asking anything, validates paths and timezone, re-runs safely and has a non-interactive mode. Ideally the machine questions move into the browser too.
- **Playback on modest machines.** Intel and AMD transcoding overlays; a sensible default streaming bitrate with an "original quality" option; direct play when the browser can decode the file; optionally an H.264 copy made overnight. (Docker on macOS cannot reach the Mac's video hardware. A Mac host would need Jellyfin running natively for that.)
- Pin the third-party images to known-good versions per release, rather than `:latest`.

## Licence

MIT for everything in this repository. The projects it runs are listed with their licences in [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Letterboxd or TMDB.
