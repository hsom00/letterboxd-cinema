# Letterboxd Cinema

**Add a film to your Letterboxd watchlist. A little later, it's waiting for you in your own cinema.**

Letterboxd Cinema is a private cinema that runs on a computer in your home. It watches your Letterboxd watchlist, finds and fetches each film, files it neatly, and shows it to you the way a film deserves: full-screen stills, a few lines about it, a rating in white stars, and a Play button that dims the lights. No folders to manage, no torrent clients to babysit, no settings pages full of jargon. You keep a watchlist; you get a cinema.

It's for people who love films and would rather not become sysadmins to watch them.

## What it feels like

- **Now showing** — one film at a time, full-bleed, like walking past the posters. Scroll to the next.
- **All films** — the whole collection as a grid, sortable, filterable by country.
- **Random** — can't decide? One press.
- **Play** — the page dims to black and the film starts, right there. Subtitles and audio tracks where the film has them. It remembers where you stopped, on every device.
- Ratings come from Letterboxd. Countries come from where a film was actually made, not just who co-produced it.

It works in any browser, at home or away, and the Jellyfin apps on your TV and phone work with it too.

## What you need

- A computer that can stay switched on — a desktop PC, a Mac mini, an old laptop, a little home server. Windows, macOS or Linux.
- Space for films. A big drive, or a folder on one.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed on that computer. It's free; the cinema runs inside it.
- Optional: your own web address (a domain on Cloudflare) if you want to watch from anywhere. Optional: an NVIDIA graphics card, if you want smoother playback on phones and slow connections.

## Setting it up

1. **Get the code.** In a terminal (PowerShell on Windows, Terminal on Mac):
   ```
   git clone https://github.com/hsom00/letterboxd-cinema
   cd letterboxd-cinema
   ```
2. **Run the installer.** It asks where to keep films and settings, your timezone, whether this is for home only or the whole internet, and whether you have an NVIDIA card. Defaults are fine.
   ```
   .\scripts\install.ps1        # Windows
   bash scripts/install.sh      # Mac / Linux
   ```
   The first start downloads everything it needs; give it a few minutes.
3. **Open `http://localhost`** in a browser on that computer. You'll be walked through naming your cinema, creating your account, connecting your Letterboxd, and choosing where films may come from. Then sign in.

That's it. Add something to your Letterboxd watchlist and check back in an hour.

## Everyday use

You mostly don't touch it. Films arrive from your watchlist. New versions of everything install themselves weekly. If you'd like to poke at things, your initial in the top-right corner opens **Settings**: look for new films right now, change your Letterboxd, see what's downloading, switch sources on and off, rename the cinema. Admins also get a quiet "Remove from library" at the bottom of any film page.

Watching from outside the house: either choose *public* during setup (you'll need a domain on Cloudflare and to forward two ports on your router — the installer tells you which), or keep it home-only and use [Tailscale](https://tailscale.com) on the server and your laptop, which needs no router changes at all.

A word on responsibility: the cinema fetches films from public sources you choose. What you download, and whether you may, is between you and the law where you live.

## Under the bonnet

For the curious and the technical. Everything below is optional reading.

The cinema is a thin, hand-made front-end over a stack of well-known open-source tools, pre-wired so you never have to open them: **Jellyfin** (the media server and player back-end), **Radarr** (decides what to fetch and files it), **Prowlarr** (talks to the sources), **Transmission** (does the fetching), **Decluttarr** (clears stuck downloads and tries again), **letterboxd-list-radarr** (turns a Letterboxd list into something Radarr understands), **Caddy** (serves the site and gets your HTTPS certificate), and **Watchtower** (keeps everything updated). Plus two small pieces of our own: a **helper** that fetches Letterboxd ratings and countries and handles admin actions, and a **provisioner** that configures all of the above over their APIs on first start.

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

**Paths.** `MEDIA_PATH` gets `movies/` and `downloads/`; every container sees it as `/data`, so Radarr moves a finished download into the library with a hard link rather than a copy, and Jellyfin reads the same folder read-only. `CONFIG_PATH` (default `appdata/` inside the clone) holds each service's state.

**Ports.** Only the cinema is exposed (80/443). Radarr, Prowlarr, Transmission and Jellyfin are bound to `127.0.0.1` — reachable from the machine itself at `:7878`, `:9696`, `:9091`, `:8096` — and never from the network.

**Updates.** GitHub builds the three images (`web`, `helper`, `provision`) whenever the `stable` branch moves and publishes them to `ghcr.io/hsom00/letterboxd-cinema/`. Watchtower pulls them, and the third-party images, weekly. `CHANNEL=main` in `.env` follows every commit. A change to `docker-compose.yml` itself is the one thing that needs a hand: `git pull && docker compose up -d`.

**Developing.** Set `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` in `.env` and `docker compose up -d --build`. The front-end is served straight from `web/`; edits show on refresh. `COMPOSE_PATH_SEPARATOR=:` is set by the installer so that line works on Windows too.

**Two installs on one machine** (a test next to a live one): separate folders, separate `CONFIG_PATH`, and different `HTTP_PORT`/`HTTPS_PORT`/`PEER_PORT`/`DISCOVERY_PORT`.

**Keyboard.** `R` random · `G` reel/grid · `Esc` close · in the player: `Space`, `←` `→` ±10s, `F` fullscreen, `M` mute.

## Roadmap

- **Installer, properly.** One cross-platform installer that checks Docker and ports before asking anything, validates paths and timezone, re-runs safely, and has a non-interactive mode. Ideally the machine questions move into the browser too.
- **Playback on modest machines.** Intel and AMD transcoding overlays; a sensible default streaming bitrate with an "original quality" option; prefer direct play when the browser can decode the file; optionally pre-transcode an H.264 copy overnight. (Docker on macOS can't reach the Mac's video hardware; a Mac host would need Jellyfin running natively for that.)
- Pin the third-party images to known-good versions per release, rather than `:latest`.

## Licence

MIT for everything in this repository. The projects it runs are listed with their licences in [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Letterboxd or TMDB; it just loves them.
