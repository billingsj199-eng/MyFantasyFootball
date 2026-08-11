"""Upload MFF helper zips to the Chrome Web Store via the Publish API.

Requires the one-time setup in store_api_setup.py (writes
E:\\MyFantasyFootball\\secrets\\webstore_api.json).

Usage:
  python store_upload.py sleeper espn yahoo      # upload only (draft)
  python store_upload.py --publish sleeper       # upload + submit for review
  python store_upload.py --status underdog       # show item review state

Item IDs and zip filename prefixes live in ITEMS below — update versions by
just rebuilding the zips (the newest matching zip in this folder is used).
"""
import glob
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = r"E:\MyFantasyFootball\secrets\webstore_api.json"

ITEMS = {
    "underdog": ("jflkoplljldeahkdlagncceajpgemngi", "mff-underdog-draft-helper-"),
    "sleeper":  ("diciafipnmplnociipgdogkcikoinlka", "mff-sleeper-helper-"),
    "espn":     ("fdlgcgmlkccfeinpgidblkhhkegphgbn", "mff-espn-helper-"),
    "yahoo":    ("bkoclmjfaggemegcadeplacemoekdpoi", "mff-yahoo-helper-"),
}


def _vkey(path):
    m = re.search(r"-(\d+)\.(\d+)\.(\d+)\.zip$", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def newest_zip(prefix):
    hits = glob.glob(os.path.join(HERE, prefix + "*.zip"))
    if not hits:
        raise SystemExit("No zip matching " + prefix + "*.zip")
    return max(hits, key=_vkey)


def access_token():
    cfg = json.load(open(SECRETS_PATH))
    body = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def api(method, url, token, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "x-goog-api-version": "2",
    })
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url} -> HTTP {e.code}: {e.read()[:500]}")


def main():
    args = [a for a in sys.argv[1:]]
    publish = "--publish" in args
    status_only = "--status" in args
    names = [a for a in args if not a.startswith("--")] or list(ITEMS)
    token = access_token()
    for name in names:
        item_id, prefix = ITEMS[name]
        if status_only:
            r = api("GET",
                    f"https://www.googleapis.com/chromewebstore/v1.1/items/{item_id}?projection=DRAFT",
                    token)
            print(name, "->", json.dumps(r))
            continue
        z = newest_zip(prefix)
        print(f"{name}: uploading {os.path.basename(z)} ...")
        r = api("PUT",
                f"https://www.googleapis.com/upload/chromewebstore/v1.1/items/{item_id}",
                token, data=open(z, "rb").read())
        print("  upload:", r.get("uploadState"), r.get("itemError", ""))
        if r.get("uploadState") not in ("SUCCESS", "IN_PROGRESS"):
            raise SystemExit("Upload failed for " + name)
        if publish:
            r = api("POST",
                    f"https://www.googleapis.com/chromewebstore/v1.1/items/{item_id}/publish",
                    token)
            print("  publish:", r.get("status"), r.get("statusDetail", ""))


if __name__ == "__main__":
    main()
