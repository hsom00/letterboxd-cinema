"""Letterboxd Cinema provisioner.

Configures Radarr, Prowlarr and Jellyfin over their APIs so nobody has to open them. Every step checks
before it creates, so re-running is safe. Runs two ways:
  - as a one-shot container at `docker compose up` (main below)
  - in-process from the helper, when the onboarding wizard is submitted (run())

Settings come from /data/settings.json (written by the onboarding wizard) with .env as the fallback:
  name, admin_user, admin_password, letterboxd_user, indexers[]
Environment:
  RADARR_API_KEY, PROWLARR_API_KEY   pre-seeded by the installer
  MAX_MB_PER_MINUTE                  size ceiling per quality (default 150 -> ~20 GB for a 2h15 film)
  SEED_RATIO / SEED_TIME_MINUTES     when Radarr may remove a finished torrent (default ratio 1.0)
"""
import json, os, sys, time, urllib.request, urllib.error

E = os.environ.get
RADARR, PROWLARR, JELLYFIN = E("RADARR_URL", "http://radarr:7878"), E("PROWLARR_URL", "http://prowlarr:9696"), E("JELLYFIN_URL", "http://jellyfin:8096")
RK, PK = E("RADARR_API_KEY", ""), E("PROWLARR_API_KEY", "")
MAX_MB = float(E("MAX_MB_PER_MINUTE", "150"))
SEED_RATIO, SEED_TIME = E("SEED_RATIO", "1.0"), E("SEED_TIME_MINUTES", "")
SETTINGS = E("SETTINGS_PATH", "/data/settings.json")
JF_AUTH = 'MediaBrowser Client="Letterboxd Cinema", Device="server", DeviceId="provisioner", Version="1.0"'

def load_settings():
    s = {}
    try: s = json.load(open(SETTINGS))
    except Exception: pass
    return {
        "name": s.get("name") or E("APP_NAME", "Cinema"),
        "admin_user": s.get("admin_user") or E("JELLYFIN_ADMIN_USER", ""),
        "admin_password": s.get("admin_password") or E("JELLYFIN_ADMIN_PASSWORD", ""),
        "letterboxd_user": (s.get("letterboxd_user") or E("LETTERBOXD_USER", "")).strip().strip("/"),
        "indexers": s.get("indexers") or [x.strip() for x in E("DEFAULT_INDEXERS", "").split(",") if x.strip()],
    }

LOG = []
def log(*a):
    line = " ".join(str(x) for x in a); LOG.append(line); print("provision |", line, file=sys.stderr, flush=True)

def call(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and r.headers.get("Content-Type", "").startswith("application/json") else raw.decode(errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

def wait_for(name, url, headers=None, tries=90):
    for _ in range(tries):
        try:
            code, _ = call("GET", url, headers=headers)
            if code < 500: return True
        except Exception: pass
        time.sleep(2)
    log(f"{name} did not come up in time — skipped"); return False

# ------------------------------------------------------------------ Radarr
def radarr():
    H = {"X-Api-Key": RK}
    if not RK or not wait_for("Radarr", f"{RADARR}/api/v3/system/status", H): return {}
    out = {}
    _, roots = call("GET", f"{RADARR}/api/v3/rootfolder", headers=H)
    if not any(r.get("path") == "/data/movies" for r in roots or []):
        code, _ = call("POST", f"{RADARR}/api/v3/rootfolder", {"path": "/data/movies"}, H); log("Radarr: library folder", "ok" if code < 300 else code)
    _, clients = call("GET", f"{RADARR}/api/v3/downloadclient", headers=H)
    if not any(c.get("implementation") == "Transmission" for c in clients or []):
        body = {"enable": True, "protocol": "torrent", "priority": 1, "removeCompletedDownloads": True, "removeFailedDownloads": True,
                "name": "Transmission", "implementation": "Transmission", "configContract": "TransmissionSettings",
                "fields": [{"name": "host", "value": "transmission"}, {"name": "port", "value": 9091}, {"name": "useSsl", "value": False},
                           {"name": "urlBase", "value": "/transmission/"}, {"name": "username", "value": ""}, {"name": "password", "value": ""},
                           {"name": "movieCategory", "value": ""}, {"name": "movieDirectory", "value": ""},
                           {"name": "recentMoviePriority", "value": 0}, {"name": "olderMoviePriority", "value": 0}, {"name": "addPaused", "value": False}]}
        code, r = call("POST", f"{RADARR}/api/v3/downloadclient", body, H); log("Radarr: download client", "ok" if code < 300 else f"{code} {str(r)[:160]}")
    _, naming = call("GET", f"{RADARR}/api/v3/config/naming", headers=H)
    if isinstance(naming, dict) and not naming.get("renameMovies"):
        naming.update({"renameMovies": True, "replaceIllegalCharacters": True,
                       "standardMovieFormat": "{Movie CleanTitle} ({Release Year}) {Quality Full}", "movieFolderFormat": "{Movie CleanTitle} ({Release Year})"})
        code, _ = call("PUT", f"{RADARR}/api/v3/config/naming/{naming['id']}", naming, H); log("Radarr: file naming", "ok" if code < 300 else code)
    _, mm = call("GET", f"{RADARR}/api/v3/config/mediamanagement", headers=H)
    if isinstance(mm, dict) and not (mm.get("copyUsingHardlinks") and mm.get("importExtraFiles")):
        mm.update({"copyUsingHardlinks": True, "importExtraFiles": True, "extraFileExtensions": "srt,sub,idx,ass"})
        code, _ = call("PUT", f"{RADARR}/api/v3/config/mediamanagement/{mm['id']}", mm, H); log("Radarr: hard links and subtitles", "ok" if code < 300 else code)
    _, defs = call("GET", f"{RADARR}/api/v3/qualitydefinition", headers=H)
    changed = []
    for d in defs if isinstance(defs, list) else []:
        name = d["quality"]["name"]; is4k = "2160" in name
        want_max = None if "Remux" in name else min(d.get("maxSize") or 400, MAX_MB)
        want_pref = 100 if is4k else 55
        if want_max is not None and (d.get("maxSize") != want_max or d.get("preferredSize") != min(want_pref, want_max)):
            d["maxSize"] = want_max; d["preferredSize"] = min(want_pref, want_max); changed.append(d)
    if changed:
        code, _ = call("PUT", f"{RADARR}/api/v3/qualitydefinition/update", changed, H); log(f"Radarr: size limits", "ok" if code < 300 else code)
    _, profiles = call("GET", f"{RADARR}/api/v3/qualityprofile", headers=H)
    profiles = profiles if isinstance(profiles, list) else []
    prof = next((p for p in profiles if p["name"] in ("Any", "HD-1080p", "Ultra-HD")), profiles[0] if profiles else None)
    if prof:
        touched = False
        for item in prof["items"]:
            for q in ([item] if "quality" in item else item.get("items", [])):
                if "Remux" in q["quality"]["name"] and q.get("allowed"): q["allowed"] = False; touched = True
            if "Remux" in (item.get("name") or "") and item.get("allowed"): item["allowed"] = False; touched = True
        if touched:
            code, _ = call("PUT", f"{RADARR}/api/v3/qualityprofile/{prof['id']}", prof, H); log("Radarr: quality profile", "ok" if code < 300 else code)
        out["profileId"] = prof["id"]
    return out

def radarr_import_list(lb_user, profile_id):
    if not (lb_user and RK): return
    H = {"X-Api-Key": RK}
    _, lists = call("GET", f"{RADARR}/api/v3/importlist", headers=H)
    url = f"http://letterboxd-list:5000/{lb_user}/watchlist/"
    if any(url in json.dumps(l.get("fields", [])) for l in (lists if isinstance(lists, list) else [])): return
    body = {"enabled": True, "enableAuto": True, "searchOnAdd": True, "monitor": "movieOnly", "minimumAvailability": "released",
            "rootFolderPath": "/data/movies", "qualityProfileId": profile_id or 1, "name": f"Letterboxd watchlist ({lb_user})",
            "implementation": "RadarrListImport", "configContract": "RadarrListSettings", "listType": "advanced", "listOrder": 0,
            "fields": [{"name": "url", "value": url}]}
    code, r = call("POST", f"{RADARR}/api/v3/importlist", body, H); log(f"Radarr: Letterboxd watchlist for {lb_user}", "ok" if code < 300 else f"{code} {str(r)[:160]}")

def radarr_jellyfin_notification(jf_key):
    if not (jf_key and RK): return
    H = {"X-Api-Key": RK}
    _, notes = call("GET", f"{RADARR}/api/v3/notification", headers=H)
    if any(n.get("implementation") == "MediaBrowser" for n in (notes if isinstance(notes, list) else [])): return
    body = {"name": "Jellyfin", "implementation": "MediaBrowser", "configContract": "MediaBrowserSettings",
            "onGrab": False, "onDownload": True, "onUpgrade": True, "onRename": True, "onMovieDelete": True, "onMovieFileDelete": True,
            "fields": [{"name": "host", "value": "jellyfin"}, {"name": "port", "value": 8096}, {"name": "useSsl", "value": False}, {"name": "urlBase", "value": ""},
                       {"name": "apiKey", "value": jf_key}, {"name": "notify", "value": False}, {"name": "updateLibrary", "value": True}]}
    code, r = call("POST", f"{RADARR}/api/v3/notification", body, H); log("Radarr: tell Jellyfin about new films", "ok" if code < 300 else f"{code} {str(r)[:160]}")

# ------------------------------------------------------------------ Prowlarr
def prowlarr_public_indexers():
    """Public, movie-capable indexer definitions Prowlarr knows about — for the onboarding wizard's choice list."""
    H = {"X-Api-Key": PK}
    if not PK: return []
    _, schema = call("GET", f"{PROWLARR}/api/v1/indexer/schema", headers=H)
    out = []
    for s in schema if isinstance(schema, list) else []:
        if s.get("privacy") != "public": continue
        cats = [c.get("id", 0) for c in (s.get("capabilities") or {}).get("categories", [])]
        if not any(2000 <= c < 3000 for c in cats): continue
        text = f"{s.get('name', '')} {s.get('description', '')}".lower()
        if "anime" in text or "hentai" in text: continue           # not much use for a film library
        if (s.get("language") or "en-US") != "en-US": continue     # keep the list to English-language trackers by default
        out.append({"id": s.get("definitionName"), "name": s.get("name"), "description": (s.get("description") or "")[:120], "language": s.get("language")})
    return sorted(out, key=lambda x: (x["name"] or "").lower())

def prowlarr(indexers):
    H = {"X-Api-Key": PK}
    if not (PK and RK) or not wait_for("Prowlarr", f"{PROWLARR}/api/v1/system/status", H): return
    _, apps = call("GET", f"{PROWLARR}/api/v1/applications", headers=H)
    if not any(a.get("implementation") == "Radarr" for a in (apps if isinstance(apps, list) else [])):
        body = {"name": "Radarr", "implementation": "Radarr", "configContract": "RadarrSettings", "syncLevel": "fullSync",
                "fields": [{"name": "prowlarrUrl", "value": "http://prowlarr:9696"}, {"name": "baseUrl", "value": "http://radarr:7878"},
                           {"name": "apiKey", "value": RK}, {"name": "syncCategories", "value": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080]}]}
        code, r = call("POST", f"{PROWLARR}/api/v1/applications", body, H); log("Prowlarr: linked to Radarr", "ok" if code < 300 else f"{code} {str(r)[:160]}")
    if indexers:
        _, have = call("GET", f"{PROWLARR}/api/v1/indexer", headers=H)
        have_names = {(i.get("definitionName") or "").lower() for i in (have if isinstance(have, list) else [])}
        _, schema = call("GET", f"{PROWLARR}/api/v1/indexer/schema", headers=H)
        for want in indexers:
            if want.lower() in have_names: continue
            d = next((s for s in (schema if isinstance(schema, list) else []) if (s.get("definitionName") or "").lower() == want.lower() or (s.get("name") or "").lower() == want.lower()), None)
            if not d: log(f"Prowlarr: no source called '{want}'"); continue
            d["enable"] = True; d["appProfileId"] = d.get("appProfileId") or 1; d["name"] = d.get("name") or want
            for f in d.get("fields", []):
                if f.get("name") == "torrentBaseSettings.seedRatio" and SEED_RATIO: f["value"] = float(SEED_RATIO)
                if f.get("name") == "torrentBaseSettings.seedTime" and SEED_TIME: f["value"] = int(SEED_TIME)
            code, r = call("POST", f"{PROWLARR}/api/v1/indexer", d, H)
            if code < 300: log(f"Prowlarr: source {d['name']}", "ok"); continue
            # Prowlarr tests a source before saving; public trackers come and go. Keep it, but switched off, so it can be enabled later.
            why = "blocked by Cloudflare" if "cloudflare" in str(r).lower() else "unreachable right now"
            d["enable"] = False
            code2, _ = call("POST", f"{PROWLARR}/api/v1/indexer?forceSave=true", d, H)
            log(f"Prowlarr: source {d['name']}", f"{why} — added but switched off" if code2 < 300 else f"{why} — skipped")
    call("POST", f"{PROWLARR}/api/v1/command", {"name": "ApplicationIndexerSync"}, H)

# ------------------------------------------------------------------ Jellyfin
def jellyfin_needs_setup():
    try:
        code, info = call("GET", f"{JELLYFIN}/System/Info/Public")
        return code == 200 and isinstance(info, dict) and not info.get("StartupWizardCompleted")
    except Exception: return False

def jellyfin(admin_user, admin_pass):
    if not wait_for("Jellyfin", f"{JELLYFIN}/System/Info/Public"): return None
    H = {"Authorization": JF_AUTH}
    if jellyfin_needs_setup():
        if not (admin_user and admin_pass): log("Jellyfin: no account chosen yet — its own wizard is still waiting"); return None
        call("POST", f"{JELLYFIN}/Startup/Configuration", {"UICulture": "en-GB", "MetadataCountryCode": "GB", "PreferredMetadataLanguage": "en"}, H)
        call("GET", f"{JELLYFIN}/Startup/User", headers=H)
        code, _ = call("POST", f"{JELLYFIN}/Startup/User", {"Name": admin_user, "Password": admin_pass}, H); log(f"Jellyfin: account {admin_user}", "ok" if code < 300 else code)
        call("POST", f"{JELLYFIN}/Startup/RemoteAccess", {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False}, H)
        code, _ = call("POST", f"{JELLYFIN}/Startup/Complete", headers=H); log("Jellyfin: setup complete", "ok" if code < 300 else code)
        time.sleep(3)
    if not (admin_user and admin_pass): return None
    code, auth = call("POST", f"{JELLYFIN}/Users/AuthenticateByName", {"Username": admin_user, "Pw": admin_pass}, H)
    if code != 200: log(f"Jellyfin: could not sign in as {admin_user} — library not checked"); return None
    T = {"X-Emby-Token": auth["AccessToken"]}
    _, libs = call("GET", f"{JELLYFIN}/Library/VirtualFolders", headers=T)
    if not any("/data/movies" in (l.get("Locations") or []) for l in (libs if isinstance(libs, list) else [])):
        body = {"LibraryOptions": {"EnableRealtimeMonitor": True, "PathInfos": [{"Path": "/data/movies"}], "MetadataCountryCode": "GB", "PreferredMetadataLanguage": "en",
                "TypeOptions": [{"Type": "Movie", "ImageOptions": [{"Type": "Backdrop", "Limit": 5, "MinWidth": 1280}, {"Type": "Primary", "Limit": 1, "MinWidth": 0}]}]}}
        code, _ = call("POST", f"{JELLYFIN}/Library/VirtualFolders?name=Movies&collectionType=movies&refreshLibrary=true", body, T); log("Jellyfin: Movies library", "ok" if code < 300 else code)
    # Folder watching doesn't work through Docker Desktop's file sharing, so scan on a short timer instead
    _, tasks = call("GET", f"{JELLYFIN}/ScheduledTasks", headers=T)
    scan = next((t for t in (tasks if isinstance(tasks, list) else []) if t.get("Key") == "RefreshLibrary"), None)
    if scan:
        fifteen = 15 * 60 * 10000000
        if not any(tr.get("Type") == "IntervalTrigger" and tr.get("IntervalTicks") == fifteen for tr in scan.get("Triggers", [])):
            code, _ = call("POST", f"{JELLYFIN}/ScheduledTasks/{scan['Id']}/Triggers", [{"Type": "IntervalTrigger", "IntervalTicks": fifteen}, {"Type": "StartupTrigger"}], T)
            log("Jellyfin: scan for new films every 15 minutes", "ok" if code < 300 else code)
    call("POST", f"{JELLYFIN}/Library/Refresh", headers=T)
    _, keys = call("GET", f"{JELLYFIN}/Auth/Keys", headers=T)
    find = lambda ks: next((k["AccessToken"] for k in (ks or {}).get("Items", []) if k.get("AppName") == "Radarr"), None) if isinstance(ks, dict) else None
    key = find(keys)
    if not key:
        call("POST", f"{JELLYFIN}/Auth/Keys?app=Radarr", headers=T)
        _, keys = call("GET", f"{JELLYFIN}/Auth/Keys", headers=T); key = find(keys)
    return key

# ------------------------------------------------------------------ run
def run():
    LOG.clear()
    s = load_settings()
    r = radarr()
    prowlarr(s["indexers"])
    jf_key = jellyfin(s["admin_user"], s["admin_password"])
    radarr_import_list(s["letterboxd_user"], r.get("profileId") if r else None)
    radarr_jellyfin_notification(jf_key)
    if not LOG: log("Everything was already set up")
    return list(LOG)

if __name__ == "__main__":
    log("starting")
    run()
    log("done")
