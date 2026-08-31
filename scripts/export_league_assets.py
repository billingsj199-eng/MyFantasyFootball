#!/usr/bin/env python3
"""Export a fantasy league's team list + avatar images for graphics-making.

Supports ESPN and Sleeper. Writes an out folder containing:
  teams.json          - [{id, name, abbrev, division, managers, logo_url, logo_file}]
  avatars/<id>.<ext>  - downloaded avatar images

Usage:
  # Sleeper (always works - public API):
  python scripts/export_league_assets.py --platform sleeper --league 123456789012345678

  # ESPN public league:
  python scripts/export_league_assets.py --platform espn --league 114487 --year 2026

  # ESPN private league: log in, open the mTeam URL, Ctrl+S the JSON, then:
  python scripts/export_league_assets.py --platform espn --league 114487 --json "E:\\Downloads\\114487.json"
  #   mTeam URL: https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<YEAR>/segments/0/leagues/<ID>?view=mTeam

ESPN custom-uploaded logos (mystique-api URLs) are only served to logged-in
members; those download as FAIL here. Save each one manually into the avatars
folder as <teamId>.<anything> and re-run - the script picks up existing files
and fills teams.json accordingly.
"""
import argparse, json, os, re, sys, glob

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

EXT_BY_TYPE = {"svg": "svg", "jpeg": "jpg", "jpg": "jpg", "gif": "gif", "webp": "webp", "png": "png"}


def pick_ext(content_type):
    for key, ext in EXT_BY_TYPE.items():
        if key in (content_type or ""):
            return ext
    return "png"


def existing_avatar(avdir, team_id):
    hits = glob.glob(os.path.join(avdir, f"{team_id}.*"))
    return os.path.basename(hits[0]) if hits else None


def download_avatar(url, avdir, team_id):
    """Returns (logo_file, note). Falls back to a pre-existing manual file on failure."""
    if not url:
        return existing_avatar(avdir, team_id), "no logo url"
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://fantasy.espn.com/"}, timeout=20)
        r.raise_for_status()
        ext = pick_ext(r.headers.get("Content-Type"))
        fname = f"{team_id}.{ext}"
        with open(os.path.join(avdir, fname), "wb") as f:
            f.write(r.content)
        return fname, "ok"
    except Exception as e:
        manual = existing_avatar(avdir, team_id)
        if manual:
            return manual, "using manually saved file"
        return None, f"FAIL ({e}) - save manually as avatars/{team_id}.png"


def export_espn(league_id, year, json_path, avdir):
    if json_path:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):  # some saves wrap the payload in a list
            data = data[0]
    else:
        url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}"
               f"/segments/0/leagues/{league_id}?view=mTeam")
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        if r.status_code == 401:
            sys.exit("ESPN says private (401). Open the mTeam URL in your logged-in browser, "
                     "Ctrl+S the JSON, and re-run with --json <path>. See --help for the URL.")
        r.raise_for_status()
        data = r.json()

    members = {m.get("id"): m for m in data.get("members", [])}

    def member_name(guid):
        m = members.get(guid, {})
        full = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
        return full or m.get("displayName", "")

    teams = []
    for t in data.get("teams", []):
        name = (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}").strip()
        name = re.sub(r"\s+", " ", name)
        managers = list(dict.fromkeys(n for n in (member_name(g) for g in t.get("owners", [])) if n))
        teams.append({
            "id": t.get("id"),
            "name": name,
            "abbrev": t.get("abbrev", ""),
            "division": f"Division {t.get('divisionId')}" if t.get("divisionId") is not None else "",
            "managers": managers,
            "logo_url": t.get("logo", ""),
        })
    return teams


def export_sleeper(league_id, avdir):
    base = f"https://api.sleeper.app/v1/league/{league_id}"
    league = requests.get(base, timeout=20).json()
    users = requests.get(base + "/users", timeout=20).json()
    rosters = requests.get(base + "/rosters", timeout=20).json()

    div_names = {}
    for i in range(1, 13):
        n = (league.get("metadata") or {}).get(f"division_{i}")
        if n:
            div_names[i] = n

    users_by_id = {u["user_id"]: u for u in users}

    def avatar_url(user):
        meta = user.get("metadata") or {}
        if str(meta.get("avatar", "")).startswith("http"):
            return meta["avatar"]  # custom team avatar
        if user.get("avatar"):
            return f"https://sleepercdn.com/avatars/{user['avatar']}"
        return ""

    teams = []
    for r in rosters:
        owner = users_by_id.get(r.get("owner_id"), {})
        meta = owner.get("metadata") or {}
        name = meta.get("team_name") or owner.get("display_name") or f"Roster {r['roster_id']}"
        managers = [owner.get("display_name", "")]
        for co in (r.get("co_owners") or []):
            co_u = users_by_id.get(co)
            if co_u:
                managers.append(co_u.get("display_name", ""))
        div = (r.get("settings") or {}).get("division")
        teams.append({
            "id": r["roster_id"],
            "name": name,
            "abbrev": "",
            "division": div_names.get(div, f"Division {div}" if div else ""),
            "managers": [m for m in managers if m],
            "logo_url": avatar_url(owner),
        })
    return teams


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", required=True, choices=["espn", "sleeper"])
    ap.add_argument("--league", required=True, help="league id")
    ap.add_argument("--year", type=int, default=2026, help="ESPN season year (default 2026)")
    ap.add_argument("--json", help="ESPN only: path to a saved mTeam JSON (for private leagues)")
    ap.add_argument("--out", default=None, help="output folder (default league_exports/<platform>_<id>)")
    args = ap.parse_args()

    out = args.out or os.path.join("league_exports", f"{args.platform}_{args.league}")
    avdir = os.path.join(out, "avatars")
    os.makedirs(avdir, exist_ok=True)

    if args.platform == "espn":
        teams = export_espn(args.league, args.year, args.json, avdir)
    else:
        teams = export_sleeper(args.league, avdir)

    manual_needed = []
    for t in teams:
        fname, note = download_avatar(t["logo_url"], avdir, t["id"])
        t["logo_file"] = fname
        print(f"  [{t['id']:>2}] {t['name']:<32} {t['division']:<12} {', '.join(t['managers']):<38} {note}")
        if fname is None:
            manual_needed.append(t)

    with open(os.path.join(out, "teams.json"), "w", encoding="utf-8") as f:
        json.dump(teams, f, indent=2, ensure_ascii=False)

    print(f"\n{len(teams)} teams -> {os.path.join(out, 'teams.json')}")
    print(f"avatars -> {avdir}")
    if manual_needed:
        print(f"\n{len(manual_needed)} avatar(s) need a manual save (open in your logged-in browser, "
              f"right-click > Save image as... into the avatars folder):")
        for t in manual_needed:
            print(f"  save as {t['id']}.png : {t['logo_url']}")
        print("then re-run this command - existing files are picked up automatically.")


if __name__ == "__main__":
    main()
