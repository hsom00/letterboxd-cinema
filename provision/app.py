"""Letterboxd Cinema provisioner.

Runs once at `docker compose up`, after the services are reachable, and configures them over their APIs so
nobody has to open Radarr, Prowlarr or Jellyfin. Every step checks before it creates, so re-running is safe.

Reads from the environment (.env):
  RADARR_API_KEY, PROWLARR_API_KEY            pre-seeded by the installer
  JELLYFIN_ADMIN_USER, JELLYFIN_ADMIN_PASSWORD  the account the cinema signs in with (created if Jellyfin is fresh)
  LETTERBOXD_USER                              optional: that user's Letterboxd watchlist becomes a Radarr import list
  DEFAULT_INDEXERS                             optional: comma-separated Prowlarr definition names to add (public indexers)
  MAX_MB_PER_MINUTE                            size ceiling per quality (default 150 -> ~20 GB for a 2h15 film)
  SEED_RATIO / SEED_TIME_MINUTES               when Radarr may remove a finished torrent (default ratio 1.0)
"""
import json, os, sys, time, urllib.request, urllib.error

E = os.environ.get
RADARR, PROWLARR, JELLYFIN = "http://radarr:7878", "http://prowlarr:9696", "http://jellyfin:8096"
RK, PK = E("RADARR_API_KEY", ""), E("PROWLARR_API_KEY", "")
ADMIN_USER, ADMIN_PASS = E("JELLYFIN_ADMIN_USER", ""), E("JELLYFIN_ADMIN_PASSWORD", "")
LB_USER = E("LETTERBOXD_USER", "").strip().strip("/")
INDEXERS = [x.strip() for x in E("DEFAULT_INDEXERS", "").split(",") if x.strip()]
MAX_MB = float(E("MAX_MB_PER_MINUTE", "150"))
SEED_RATIO, SEED_TIME = E("SEED_RATIO", "1.0"), E("SEED_TIME_MINUTES", "")
STATE = "/data/provisioned.json"
JF_AUTH = 'MediaBrowser Client="Letterboxd Cinema Provisioner", Device="server", DeviceId="provisioner", Version="1.0"'

def log(*a): print("provision |", *a, file=sys.stderr, flush=True)

def call(method, url, body=None, headers=None, ok=(200, 201, 202, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and r.headers.get("Content-Type", "").startswith("application/json") else raw.decode(errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

def wait_for(name, url, headers=None, tries=90):
    for i in range(tries):
        try:
            code, _ = call("GET", url, headers=headers)
            if code < 500: log(f"{name} is up"); return True
        except Exception: pass
        time.sleep(2)
    log(f"{name} did not come up in time — skipping"); return False

# ------------------------------------------------------------------ Radarr
def radarr():
    H = {"X-Api-Key": RK}
    if not RK or not wait_for("Radarr", f"{RADARR}/api/v3/system/status", H): return {}
    out = {}
    # root folder
    _, roots = call("GET", f"{RADARR}/api/v3/rootfolder", headers=H)
    if not any(r.get("path") == "/data/movies" for r in roots or []):
        code, r = call("POST", f"{RADARR}/api/v3/rootfolder", {"path": "/data/movies"}, H); log("radarr root folder:", code)
    # download client
    _, clients = call("GET", f"{RADARR}/api/v3/downloadclient", headers=H)
    if not any(c.get("implementation") == "Transmission" for c in clients or []):
        body = {"enable": True, "protocol": "torrent", "priority": 1, "removeCompletedDownloads": True, "removeFailedDownloads": True,
                "name": "Transmission", "implementation": "Transmission", "configContract": "TransmissionSettings",
                "fields": [{"name": "host", "value": "transmission"}, {"name": "port", "value": 9091}, {"name": "useSsl", "value": False},
                           {"name": "urlBase", "value": "/transmission/"}, {"name": "username", "value": ""}, {"name": "password", "value": ""},
                           {"name": "movieCategory", "value": ""}, {"name": "movieDirectory", "value": ""},
                           {"name": "recentMoviePriority", "value": 0}, {"name": "olderMoviePriority", "value": 0}, {"name": "addPaused", "value": False}]}
        code, r = call("POST", f"{RADARR}/api/v3/downloadclient", body, H); log("radarr download client:", code, "" if code < 300 else r)
    # naming
    _, naming = call("GET", f"{RADARR}/api/v3/config/naming", headers=H)
    if naming and not naming.get("renameMovies"):
        naming.update({"renameMovies": True, "replaceIllegalCharacters": True,
                       "standardMovieFormat": "{Movie CleanTitle} ({Release Year}) {Quality Full}", "movieFolderFormat": "{Movie CleanTitle} ({Release Year})"})
        code, _ = call("PUT", f"{RADARR}/api/v3/config/naming/{naming['id']}", naming, H); log("radarr naming:", code)
    # media management: hardlinks, bring subtitles along
    _, mm = call("GET", f"{RADARR}/api/v3/config/mediamanagement", headers=H)
    if mm and not (mm.get("copyUsingHardlinks") and mm.get("importExtraFiles")):
        mm.update({"copyUsingHardlinks": True, "importExtraFiles": True, "extraFileExtensions": "srt,sub,idx,ass"})
        code, _ = call("PUT", f"{RADARR}/api/v3/config/mediamanagement/{mm['id']}", mm, H); log("radarr media management:", code)
    # size ceilings per quality
    _, defs = call("GET", f"{RADARR}/api/v3/qualitydefinition", headers=H)
    changed = []
    for d in defs or []:
        name = d["quality"]["name"]; is4k = "2160" in name
        want_max = None if "Remux" in name else min(d.get("maxSize") or 400, MAX_MB)
        want_pref = 100 if is4k else 55
        if want_max is not None and (d.get("maxSize") != want_max or d.get("preferredSize") != min(want_pref, want_max)):
            d["maxSize"] = want_max; d["preferredSize"] = min(want_pref, want_max); changed.append(d)
    if changed:
        code, r = call("PUT", f"{RADARR}/api/v3/qualitydefinition/update", changed, H); log(f"radarr size limits ({len(changed)} qualities):", code)
    # quality profile: no remuxes, allow upgrades
    _, profiles = call("GET", f"{RADARR}/api/v3/qualityprofile", headers=H)
    prof = next((p for p in profiles or [] if p["name"] in ("Any", "HD-1080p", "Ultra-HD")), (profiles or [None])[0])
    if prof:
        touched = False
        for item in prof["items"]:
            for q in ([item] if "quality" in item else item.get("items", [])):
                if "Remux" in q["quality"]["name"] and q.get("allowed"): q["allowed"] = False; touched = True
            if "Remux" in item.get("name", "") and item.get("allowed"): item["allowed"] = False; touched = True
        if touched:
            code, r = call("PUT", f"{RADARR}/api/v3/qualityprofile/{prof['id']}", prof, H); log("radarr quality profile:", code)
        out["profileId"] = prof["id"]
    return out

def radarr_import_list(profile_id):
    if not (LB_USER and RK): return
    H = {"X-Api-Key": RK}
    _, lists = call("GET", f"{RADARR}/api/v3/importlist", headers=H)
    url = f"http://letterboxd-list:5000/{LB_USER}/watchlist/"
    if any(url in json.dumps(l.get("fields", [])) for l in lists or []): return
    body = {"enabled": True, "enableAuto": True, "searchOnAdd": True, "monitor": "movieOnly", "minimumAvailability": "released",
            "rootFolderPath": "/data/movies", "qualityProfileId": profile_id or 1, "name": f"Letterboxd watchlist ({LB_USER})",
            "implementation": "RadarrListImport", "configContract": "RadarrListSettings", "listType": "advanced", "listOrder": 0,
            "fields": [{"name": "url", "value": url}]}
    code, r = call("POST", f"{RADARR}/api/v3/importlist", body, H); log("radarr letterboxd watchlist:", code, "" if code < 300 else r)

def radarr_jellyfin_notification(jf_key):
    if not (jf_key and RK): return
    H = {"X-Api-Key": RK}
    _, notes = call("GET", f"{RADARR}/api/v3/notification", headers=H)
    if any(n.get("implementation") == "MediaBrowser" for n in notes or []): return
    body = {"name": "Jellyfin", "implementation": "MediaBrowser", "configContract": "MediaBrowserSettings",
            "onGrab": False, "onDownload": True, "onUpgrade": True, "onRename": True, "onMovieDelete": True, "onMovieFileDelete": True,
            "fields": [{"name": "host", "value": "jellyfin"}, {"name": "port", "value": 8096}, {"name": "useSsl", "value": False},
                       {"name": "apiKey", "value": jf_key}, {"name": "notify", "value": False}, {"name": "updateLibrary", "value": True}]}
    code, r = call("POST", f"{RADARR}/api/v3/notification", body, H); log("radarr -> jellyfin library refresh:", code, "" if code < 300 else r)

# ------------------------------------------------------------------ Prowlarr
def prowlarr():
    H = {"X-Api-Key": PK}
    if not (PK and RK) or not wait_for("Prowlarr", f"{PROWLARR}/api/v1/system/status", H): return
    _, apps = call("GET", f"{PROWLARR}/api/v1/applications", headers=H)
    if not any(a.get("implementation") == "Radarr" for a in apps or []):
        body = {"name": "Radarr", "implementation": "Radarr", "configContract": "RadarrSettings", "syncLevel": "fullSync",
                "fields": [{"name": "prowlarrUrl", "value": "http://prowlarr:9696"}, {"name": "baseUrl", "value": "http://radarr:7878"},
                           {"name": "apiKey", "value": RK}, {"name": "syncCategories", "value": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080]}]}
        code, r = call("POST", f"{PROWLARR}/api/v1/applications", body, H); log("prowlarr -> radarr link:", code, "" if code < 300 else r)
    if INDEXERS:
        _, have = call("GET", f"{PROWLARR}/api/v1/indexer", headers=H)
        have_names = {i.get("definitionName", "").lower() for i in have or []}
        _, schema = call("GET", f"{PROWLARR}/api/v1/indexer/schema", headers=H)
        for want in INDEXERS:
            if want.lower() in have_names: continue
            d = next((s for s in schema or [] if s.get("definitionName", "").lower() == want.lower() or s.get("name", "").lower() == want.lower()), None)
            if not d: log(f"prowlarr: no definition called '{want}'"); continue
            d["enable"] = True; d["appProfileId"] = d.get("appProfileId") or 1; d["name"] = d.get("name") or want
            for f in d.get("fields", []):
                if f.get("name") == "torrentBaseSettings.seedRatio" and SEED_RATIO: f["value"] = float(SEED_RATIO)
                if f.get("name") == "torrentBaseSettings.seedTime" and SEED_TIME: f["value"] = int(SEED_TIME)
            code, r = call("POST", f"{PROWLARR}/api/v1/indexer", d, H); log(f"prowlarr indexer {want}:", code, "" if code < 300 else str(r)[:200])
    call("POST", f"{PROWLARR}/api/v1/command", {"name": "ApplicationIndexerSync"}, H)

# ------------------------------------------------------------------ Jellyfin
def jellyfin():
    if not wait_for("Jellyfin", f"{JELLYFIN}/System/Info/Public"): return None
    H = {"Authorization": JF_AUTH}
    _, info = call("GET", f"{JELLYFIN}/System/Info/Public")
    if info and not info.get("StartupWizardCompleted"):
        if not (ADMIN_USER and ADMIN_PASS): log("jellyfin: fresh install but no JELLYFIN_ADMIN_USER/PASSWORD set — leaving its wizard for you"); return None
        call("POST", f"{JELLYFIN}/Startup/Configuration", {"UICulture": "en-GB", "MetadataCountryCode": "GB", "PreferredMetadataLanguage": "en"}, H)
        call("GET", f"{JELLYFIN}/Startup/User", headers=H)
        code, r = call("POST", f"{JELLYFIN}/Startup/User", {"Name": ADMIN_USER, "Password": ADMIN_PASS}, H); log("jellyfin admin user:", code)
        call("POST", f"{JELLYFIN}/Startup/RemoteAccess", {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False}, H)
        code, _ = call("POST", f"{JELLYFIN}/Startup/Complete", headers=H); log("jellyfin wizard completed:", code)
        time.sleep(3)
    if not (ADMIN_USER and ADMIN_PASS): return None
    code, auth = call("POST", f"{JELLYFIN}/Users/AuthenticateByName", {"Username": ADMIN_USER, "Pw": ADMIN_PASS}, H)
    if code != 200: log("jellyfin: could not sign in as", ADMIN_USER, "— skipping library setup"); return None
    T = {"X-Emby-Token": auth["AccessToken"]}
    # library
    _, libs = call("GET", f"{JELLYFIN}/Library/VirtualFolders", headers=T)
    if not any("/data/movies" in (l.get("Locations") or []) for l in libs or []):
        body = {"LibraryOptions": {"EnableRealtimeMonitor": True, "PathInfos": [{"Path": "/data/movies"}], "MetadataCountryCode": "GB", "PreferredMetadataLanguage": "en",
                "TypeOptions": [{"Type": "Movie", "ImageOptions": [{"Type": "Backdrop", "Limit": 5, "MinWidth": 1280}, {"Type": "Primary", "Limit": 1, "MinWidth": 0}]}]}}
        code, r = call("POST", f"{JELLYFIN}/Library/VirtualFolders?name=Movies&collectionType=movies&refreshLibrary=true", body, T); log("jellyfin movies library:", code)
    # api key for radarr's "library updated" nudge
    _, keys = call("GET", f"{JELLYFIN}/Auth/Keys", headers=T)
    key = next((k["AccessToken"] for k in (keys or {}).get("Items", []) if k.get("AppName") == "Radarr"), None)
    if not key:
        call("POST", f"{JELLYFIN}/Auth/Keys?app=Radarr", headers=T)
        _, keys = call("GET", f"{JELLYFIN}/Auth/Keys", headers=T)
        key = next((k["AccessToken"] for k in (keys or {}).get("Items", []) if k.get("AppName") == "Radarr"), None)
    return key

# ------------------------------------------------------------------ main
if __name__ == "__main__":
    log("starting")
    r = radarr()
    prowlarr()
    jf_key = jellyfin()
    radarr_import_list(r.get("profileId") if r else None)
    radarr_jellyfin_notification(jf_key)
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"at": time.time(), "letterboxd_user": LB_USER, "indexers": INDEXERS}, open(STATE, "w"))
    except Exception: pass
    log("done")
