#!/usr/bin/env python3
"""
upload_2027_list.py - puts the Sim Lab's 2027 list on the site's admin-only 2027 tab.
Jack 2026-11-24: "make it so I dont have to load a file and its just on the site".

It POSTs preseason2027/output/2027_inhouse_early.csv to the key-gated Cloud Function
importSim2027, which writes the private doc the 2027 tab reads (admin_sims/rankings_2027,
readable by Jack's account only). Same key file as the other PC feeds; no Google
credential on disk, nothing goes into git, and the list never touches the public repo.

  python upload_2027_list.py            # upload (the function skips an identical file)
  python upload_2027_list.py --status   # what the site has now (no upload)
  python upload_2027_list.py --force    # allow a list that lost 20%+ of its rows

Exit 0 = the site has this file (uploaded or already identical), 1 = it does not.
Called by list_2027_refresh.ps1 after a good rebuild. Stdlib only (runs on either Python).
"""
import hashlib, json, os, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "preseason2027", "output", "2027_inhouse_early.csv")
KEY_FILE = os.environ.get("MFF_EXPORT_KEY_FILE", r"E:\MyFantasyFootball\secrets\export_feed_key.txt")
FN_URL = "https://us-central1-jackb933-website.cloudfunctions.net/importSim2027"


def call(key, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(FN_URL, data=data, method="POST" if body is not None else "GET",
                                 headers={"x-export-key": key, "Content-Type": "application/json", "User-Agent": "mff-2027-list/1"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode("utf-8"))
        except Exception: return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def main():
    args = sys.argv[1:]
    try:
        key = open(KEY_FILE, encoding="utf-8").read().strip()
    except Exception as e:
        print(f"FAILED: key file not readable ({type(e).__name__})"); return 1
    if not key:
        print("FAILED: key file is empty"); return 1
    if "--status" in args:
        code, j = call(key)
        print(f"site: HTTP {code} " + json.dumps(j)); return 0 if code == 200 else 1
    if not os.path.exists(LIST):
        print(f"FAILED: {LIST} is missing"); return 1
    raw = open(LIST, "rb").read()
    csv = raw.decode("utf-8-sig")
    # The function hashes the text it receives; hash the same text here so the two can be compared.
    sha = hashlib.sha1(csv.encode("utf-8")).hexdigest()
    body = {"csv": csv, "fileName": os.path.basename(LIST), "fileDate": int(os.path.getmtime(LIST) * 1000)}
    if "--force" in args: body["force"] = True
    code, j = call(key, body)
    if code == 200 and j.get("ok") and j.get("sha1") == sha:
        what = "already on the site (identical file)" if j.get("unchanged") else "uploaded"
        print(f"OK: {what}: {j.get('rowCount')} rows, saved {j.get('savedAt')}"); return 0
    if code == 200 and j.get("ok"):
        print(f"FAILED: the site answered ok but holds a different file (site {j.get('sha1')}, local {sha})"); return 1
    print(f"FAILED: HTTP {code} " + json.dumps(j)); return 1


if __name__ == "__main__":
    sys.exit(main())
