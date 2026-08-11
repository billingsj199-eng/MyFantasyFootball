"""One-time Chrome Web Store Publish API setup (run by JACK, interactively).

After this runs once, Claude sessions can upload store zips programmatically
via store_upload.py — no more manual dashboard uploads.

Steps this walks you through:
  1. You create an OAuth client (Desktop app) in Google Cloud console:
       https://console.cloud.google.com/apis/credentials?project=jackb933-website
     - First enable the API once:
       https://console.cloud.google.com/apis/library/chromewebstore.googleapis.com?project=jackb933-website
     - "Create credentials" -> "OAuth client ID" -> Application type: Desktop app.
     - Copy the Client ID + Client secret when prompted below.
     (If asked to configure the consent screen: External, add billingsj199@gmail.com
      as a test user, scope not needed there — the script requests it.)
  2. This script prints a consent URL — open it in a browser signed into the
     SAME Google account that owns the Web Store developer dashboard, approve,
     and paste the code back here.
  3. It exchanges the code for a refresh token and writes everything to
       E:\\MyFantasyFootball\\secrets\\webstore_api.json
     (outside every git repo — same folder as the export feed key).

Run:  python store_api_setup.py
"""
import json
import os
import urllib.parse
import urllib.request

SECRETS_PATH = r"E:\MyFantasyFootball\secrets\webstore_api.json"
SCOPE = "https://www.googleapis.com/auth/chromewebstore"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"  # manual copy/paste flow


def main():
    client_id = input("OAuth Client ID: ").strip()
    client_secret = input("OAuth Client secret: ").strip()
    url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )
    print("\nOpen this URL in a browser signed into the dashboard account,")
    print("approve access, and paste the code shown:\n")
    print(url + "\n")
    code = input("Code: ").strip()
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    tok = json.load(urllib.request.urlopen(req, timeout=30))
    if "refresh_token" not in tok:
        raise SystemExit("No refresh_token in response: " + json.dumps(tok))
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)
    with open(SECRETS_PATH, "w") as f:
        json.dump({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tok["refresh_token"],
        }, f, indent=2)
    print("\nSaved", SECRETS_PATH)
    print("Done — future uploads can run via store_upload.py.")


if __name__ == "__main__":
    main()
