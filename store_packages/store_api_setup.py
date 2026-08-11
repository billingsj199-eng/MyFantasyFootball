"""One-time Chrome Web Store Publish API setup (run by JACK, interactively).

After this runs once, any Claude session can upload store zips via
store_upload.py — no more manual dashboard uploads.

WHAT YOU DO (about 5 minutes, all in a browser signed into the account that
owns the Web Store developer dashboard):

  1. Enable the API (once):
       https://console.cloud.google.com/apis/library/chromewebstore.googleapis.com?project=jackb933-website
  2. Create an OAuth client:
       https://console.cloud.google.com/apis/credentials?project=jackb933-website
     "Create credentials" -> "OAuth client ID" -> Application type: Desktop app.
     (If it asks you to configure the consent screen first: User type External,
      app name anything, add billingsj199@gmail.com under Test users, save.)
     Copy the Client ID and Client secret.
  3. Run this script:  python store_api_setup.py
     Paste the ID + secret when prompted. Your browser opens a Google consent
     page — approve it. The script catches the redirect automatically (modern
     loopback flow; nothing to copy) and writes the credentials to
       E:\\MyFantasyFootball\\secrets\\webstore_api.json
     (outside every git repo, same folder as the export feed key).

Then uploads work forever after:
  python store_upload.py --publish sleeper espn yahoo underdog
"""
import http.server
import json
import os
import threading
import urllib.parse
import urllib.request
import webbrowser

SECRETS_PATH = r"E:\MyFantasyFootball\secrets\webstore_api.json"
SCOPE = "https://www.googleapis.com/auth/chromewebstore"


class _CodeCatcher(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CodeCatcher.code = (q.get("code") or [None])[0]
        err = (q.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "Authorized — you can close this tab." if _CodeCatcher.code else (
            "Error: " + (err or "no code returned"))
        self.wfile.write(("<h2>" + msg + "</h2>").encode())

    def log_message(self, *_):
        pass


def main():
    client_id = input("OAuth Client ID: ").strip()
    client_secret = input("OAuth Client secret: ").strip()

    srv = http.server.HTTPServer(("127.0.0.1", 0), _CodeCatcher)
    port = srv.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })
    print("\nOpening the consent page (approve while signed into the dashboard")
    print("account). If the browser doesn't open, visit:\n\n" + url + "\n")
    webbrowser.open(url)

    print("Waiting for approval...")
    while _CodeCatcher.code is None:
        pass  # handle_request thread sets it

    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": _CodeCatcher.code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
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
    print("Done — uploads now work via store_upload.py.")


if __name__ == "__main__":
    main()
