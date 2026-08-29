"""Letterboxd Cinema helper: Letterboxd lookups, plus admin actions that need server-side secrets.

GET /<tmdb id>  ->  {"rating": 4.36, "count": 812345, "url": "https://letterboxd.com/film/…/",
                     "countries": ["Croatia", "Luxembourg", "Romania", "Czechia"], "languages": ["Romanian", "Czech", "English"]}

Letterboxd has no public API, so this follows their /tmdb/<id>/ redirect to the film page and reads the
average rating from the page's metadata. Results are cached on disk (7 days; misses 1 day) so each film is
fetched at most once a week, which keeps this polite and fast.
"""
import json, os, re, sys, time, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import provision  # the same code the one-shot provisioner runs; here it runs when the onboarding wizard is submitted

CACHE_PATH = os.environ.get("CACHE_PATH", "/data/cache.json")
SETTINGS_PATH = os.environ.get("SETTINGS_PATH", "/data/settings.json")
setup_lock = threading.Lock()

def settings():
    try: return json.load(open(SETTINGS_PATH))
    except Exception: return {}
def app_name(): return settings().get("name") or os.environ.get("APP_NAME", "Cinema")
def setup_needed():
    """True until an admin account exists: Jellyfin still on its startup wizard, or no settings saved yet."""
    return provision.jellyfin_needs_setup() or not settings().get("admin_user")
TTL_HIT, TTL_MISS = 7 * 86400, 86400
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
lock = threading.Lock()

def load_cache():
    try:
        with open(CACHE_PATH) as f: return json.load(f)
    except Exception: return {}
cache = load_cache()

def save_cache():
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f: json.dump(cache, f)
    os.replace(tmp, CACHE_PATH)

def fetch(tmdb_id):
    req = urllib.request.Request(f"https://letterboxd.com/tmdb/{tmdb_id}/", headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", "replace"); url = r.geturl()
    m = re.search(r'"ratingValue"\s*:\s*([\d.]+)', html)
    if not m:
        m = re.search(r'name="twitter:data2"\s+content="([\d.]+) out of 5"', html)
    if not m:
        return None
    count = re.search(r'"ratingCount"\s*:\s*(\d+)', html)
    countries = re.findall(r'"@type"\s*:\s*"Country"\s*,\s*"name"\s*:\s*"([^"]+)"', html)
    # language links appear primary-first on the film page
    langs, seen = [], set()
    for slug in re.findall(r'href="/films/language/([^/"]+)/"', html):
        name = slug.replace("-", " ").title()
        if name not in seen: seen.add(name); langs.append(name)
    return {"rating": round(float(m.group(1)), 2), "count": int(count.group(1)) if count else None, "url": url,
            "countries": countries, "languages": langs}

def lookup(tmdb_id):
    now = time.time()
    with lock:
        hit = cache.get(tmdb_id)
        fresh = hit and now - hit["t"] < (TTL_HIT if hit.get("data") else TTL_MISS)
        if fresh and not (hit.get("data") and "countries" not in hit["data"]):  # refetch entries from before countries were added
            return hit.get("data")
    try: data = fetch(tmdb_id)
    except urllib.error.HTTPError as e:
        data = None
        if e.code == 429: return None  # rate limited: don't cache, try again next time
    except Exception: data = None
    with lock:
        cache[tmdb_id] = {"t": now, "data": data}
        try: save_cache()
        except Exception as e: print("cache write failed:", e, file=sys.stderr)
    return data

# ---------- admin: remove a film (Radarr + Transmission + Jellyfin) ----------
RADARR_URL = os.environ.get("RADARR_URL", "http://radarr:7878")
RADARR_KEY = os.environ.get("RADARR_API_KEY", "")
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096")
TRANSMISSION_URL = os.environ.get("TRANSMISSION_URL", "http://transmission:9091")

def http(method, url, body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None), dict(r.headers)

def jellyfin_is_admin(token):
    try:
        _, me, _ = http("GET", f"{JELLYFIN_URL}/Users/Me", headers={"X-Emby-Token": token})
        return bool(me and me.get("Policy", {}).get("IsAdministrator")), me
    except Exception:
        return False, None

class Transmission:
    def __init__(self): self.sid = ""
    def call(self, method, arguments):
        for _ in range(2):
            try:
                _, res, _ = http("POST", f"{TRANSMISSION_URL}/transmission/rpc", {"method": method, "arguments": arguments}, {"X-Transmission-Session-Id": self.sid})
                return res
            except urllib.error.HTTPError as e:
                if e.code == 409: self.sid = e.headers.get("X-Transmission-Session-Id", ""); continue
                raise
        raise RuntimeError("transmission handshake failed")

def remove_film(tmdb_id):
    """Delete from Radarr (file included, and excluded from re-adding), then drop any torrents Radarr grabbed for it."""
    out = {"tmdb": tmdb_id, "radarr": None, "torrents_removed": 0, "torrents": []}
    H = {"X-Api-Key": RADARR_KEY}
    _, movies, _ = http("GET", f"{RADARR_URL}/api/v3/movie?tmdbId={tmdb_id}", headers=H)
    if not movies: out["radarr"] = "not in radarr"; return out
    mv = movies[0]; mid = mv["id"]; out["title"] = mv.get("title")
    # torrent hashes from Radarr's history for this movie
    hashes = set()
    try:
        _, hist, _ = http("GET", f"{RADARR_URL}/api/v3/history/movie?movieId={mid}", headers=H)
        for h in hist or []:
            if h.get("downloadId"): hashes.add(h["downloadId"].lower())
    except Exception as e: out["history_error"] = str(e)
    # remove from transmission (with data)
    if hashes:
        try:
            tr = Transmission()
            got = tr.call("torrent-get", {"fields": ["id", "hashString", "name"]}) or {}
            ids = [t["id"] for t in got.get("arguments", {}).get("torrents", []) if t["hashString"].lower() in hashes]
            names = [t["name"] for t in got.get("arguments", {}).get("torrents", []) if t["hashString"].lower() in hashes]
            if ids:
                tr.call("torrent-remove", {"ids": ids, "delete-local-data": True})
                out["torrents_removed"] = len(ids); out["torrents"] = names
        except Exception as e: out["transmission_error"] = str(e)
    # delete from radarr, file included, and keep it from coming back via lists
    http("DELETE", f"{RADARR_URL}/api/v3/movie/{mid}?deleteFiles=true&addImportExclusion=true", headers=H)
    out["radarr"] = "deleted"
    return out

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") == "/api/setup":
            return self.onboard()
        m = re.fullmatch(r"/api/admin/remove/(\d+)/?", self.path)
        if not m: return self.reply(404, {"error": "unknown action"})
        token = self.headers.get("X-Jellyfin-Token", "")
        ok, me = jellyfin_is_admin(token)
        if not ok: return self.reply(403, {"error": "administrators only"})
        if not RADARR_KEY: return self.reply(500, {"error": "RADARR_API_KEY not set"})
        try:
            result = remove_film(m.group(1))
            try: http("POST", f"{JELLYFIN_URL}/Library/Refresh", headers={"X-Emby-Token": token})
            except Exception: pass
            print(f"REMOVE by {me.get('Name')}: {result}", file=sys.stderr)
            self.reply(200, result)
        except Exception as e:
            self.reply(500, {"error": str(e)})

    def onboard(self):
        """Onboarding: only while no admin account exists. Saves settings, then provisions everything."""
        if not setup_needed(): return self.reply(403, {"error": "already set up"})
        try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except Exception: return self.reply(400, {"error": "bad request"})
        name, user, pw = (body.get("name") or "").strip(), (body.get("admin_user") or "").strip(), body.get("admin_password") or ""
        if not (name and user and pw): return self.reply(400, {"error": "name, username and password are required"})
        with setup_lock:
            if not setup_needed(): return self.reply(403, {"error": "already set up"})
            data = {"name": name, "admin_user": user, "admin_password": pw,
                    "letterboxd_user": (body.get("letterboxd_user") or "").strip().strip("/"),
                    "indexers": [x for x in body.get("indexers") or [] if isinstance(x, str)][:20], "at": time.time()}
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            json.dump(data, open(SETTINGS_PATH, "w"))
            try: lines = provision.run()
            except Exception as e: lines = [f"Setup hit a problem: {e}"]
        self.reply(200, {"ok": True, "log": lines})

    def do_GET(self):
        if self.path.rstrip("/") == "/api/config":
            return self.reply(200, {"name": app_name(), "setup": setup_needed()}, cache=False)
        if self.path.rstrip("/") == "/api/setup/sources":
            if not setup_needed(): return self.reply(403, {"error": "already set up"})
            try: return self.reply(200, {"sources": provision.prowlarr_public_indexers()}, cache=False)
            except Exception as e: return self.reply(200, {"sources": [], "error": str(e)}, cache=False)
        m = re.fullmatch(r"/(?:api/letterboxd/)?(\d+)/?", self.path)
        if self.path == "/health":
            return self.reply(200, {"ok": True, "cached": len(cache)})
        if not m: return self.reply(404, {"error": "expected /<tmdb id>"})
        data = lookup(m.group(1))
        self.reply(200 if data else 404, data or {"rating": None})
    def reply(self, code, obj, cache=True):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, fmt, *args): print(self.address_string(), fmt % args, file=sys.stderr)

if __name__ == "__main__":
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    print(f"helper on :8080, {len(cache)} letterboxd entries cached", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
