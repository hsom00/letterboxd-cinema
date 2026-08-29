# Third-party software

Letterboxd Cinema is MIT-licensed glue around other people's excellent work. Nothing below is modified or
redistributed by this repository: the compose file pulls each project's own published image, and every
service runs as a separate process talking to the others over HTTP. The only third-party code bundled in
our images is hls.js (in the `web` image) and the Caddy and Python base images.

| Component | Role | Licence |
|---|---|---|
| [Jellyfin](https://github.com/jellyfin/jellyfin) | media server, playback back-end | GPL-2.0 |
| [Radarr](https://github.com/Radarr/Radarr) | decides what to fetch, files it | GPL-3.0 |
| [Prowlarr](https://github.com/Prowlarr/Prowlarr) | talks to the sources | GPL-3.0 |
| [Transmission](https://github.com/transmission/transmission) (LinuxServer image) | fetching | GPL-2.0 / GPL-3.0 (MIT parts); LinuxServer images GPL-3.0 |
| [Decluttarr](https://github.com/ManiMatter/decluttarr) | clears stuck downloads | GPL-3.0 |
| [letterboxd-list-radarr](https://github.com/screeny05/letterboxd-list-radarr) | Letterboxd list → Radarr import list | MIT |
| [Valkey](https://github.com/valkey-io/valkey) | cache for the above | BSD-3-Clause |
| [Caddy](https://github.com/caddyserver/caddy) | web server, HTTPS certificates; base of our `web` image | Apache-2.0 |
| [Watchtower](https://github.com/nicholas-fedor/watchtower) (nicholas-fedor fork) | keeps images updated | Apache-2.0 |
| [cloudflare-ddns](https://github.com/favonia/cloudflare-ddns) | keeps a public hostname pointed home | Apache-2.0 |
| [hls.js](https://github.com/video-dev/hls.js) | HLS playback in the browser (bundled in `web/vendor/`) | Apache-2.0 — see `web/vendor/hls.js.LICENSE` |
| [Python](https://www.python.org/) 3.12 on Alpine | base of the `helper` and `provision` images | PSF-2.0; Alpine packages under their own licences |
| PT Serif, Inter, Jost | typefaces, loaded from Google Fonts at runtime (not bundled) | SIL Open Font License 1.1 |

## Data sources

Ratings, countries and languages are read from public Letterboxd film pages, cached for a week per film;
lists come through letterboxd-list-radarr in the same way. Letterboxd's terms of use restrict automated
access; this is a personal, low-volume tool that fetches one page per film in your own library, and you
should read those terms yourself before relying on it. Film details and artwork come from
[TMDB](https://www.themoviedb.org/) via Jellyfin under TMDB's API terms. This project is not affiliated
with, endorsed by, or sponsored by Letterboxd or TMDB.
