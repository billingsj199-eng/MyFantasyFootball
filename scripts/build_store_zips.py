"""Build Chrome Web Store upload zips for the MFF helper extensions.

Re-creation of the session-scratchpad package_store.py that LISTINGS.md
references, made permanent. Zips each extension dir FLAT (files at zip
root, no wrapper folder) excluding harness/docs files (mock*, *.md,
*.bak*, *.tmp), named mff-<listing>-<manifest version>.zip in
store_packages/ — store_upload.py picks the newest matching zip.

Usage:
    python scripts/build_store_zips.py                 # sleeper + espn + yahoo
    python scripts/build_store_zips.py underdog        # explicit only — UD is
                                                       # frozen (appeal pending)
    python scripts/build_store_zips.py sleeper espn    # subset
"""
import fnmatch
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "store_packages")
EXCLUDE = ["mock*", "*.md", "*.bak*", "*.tmp"]
# UD deliberately absent from the default set: 0.17.7 appeal pending, NO uploads.
DEFAULT = ["sleeper", "espn", "yahoo"]
EXTS = {
    "sleeper": ("sleeper-extension", "mff-sleeper-helper"),
    "espn": ("espn-extension", "mff-espn-helper"),
    "yahoo": ("yahoo-extension", "mff-yahoo-helper"),
    "underdog": ("underdog-extension", "mff-underdog-draft-helper"),
}


def excluded(rel):
    base = os.path.basename(rel)
    return any(fnmatch.fnmatch(base, pat) for pat in EXCLUDE)


def build(key):
    dirname, prefix = EXTS[key]
    src = os.path.join(ROOT, dirname)
    with open(os.path.join(src, "manifest.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    out = os.path.join(OUT_DIR, prefix + "-" + version + ".zip")
    names = []
    for dirpath, _dirs, files in os.walk(src):
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(dirpath, fn), src).replace(os.sep, "/")
            if not excluded(rel):
                names.append(rel)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(names):
            z.write(os.path.join(src, rel), rel)
    print("%s: %d files -> %s (%d KB)" % (
        key, len(names), os.path.basename(out), os.path.getsize(out) // 1024))
    return out


if __name__ == "__main__":
    keys = [k.lower() for k in sys.argv[1:]] or list(DEFAULT)
    bad = [k for k in keys if k not in EXTS]
    if bad:
        raise SystemExit("Unknown extension(s): %s (choose from %s)" % (bad, sorted(EXTS)))
    for k in keys:
        build(k)
