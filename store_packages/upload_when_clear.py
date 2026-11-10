"""Upload + submit helper zips once their pending Chrome Web Store review clears.

Jack 2026-10-05: "we'll wait, upload when they clear review". Sleeper 0.29.36 /
ESPN 0.20.47 were in review, and the store refuses any upload while an item is
pending (ITEM_NOT_UPDATABLE). Task Scheduler ("MFF Store Upload When Clear",
every 3 hours) runs this: each item still listed in upload_when_clear.json gets
`store_upload.py --publish <name>` (newest zip in this folder). A refusal
because of the pending review leaves it queued; success drops it from the
queue. With the queue empty the script deletes its own scheduled task.

Log: upload_when_clear.log (this folder).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "upload_when_clear.json")
LOG = os.path.join(HERE, "upload_when_clear.log")
TASK = "MFF Store Upload When Clear"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")


def main():
    q = json.load(open(QUEUE, encoding="utf-8")) if os.path.exists(QUEUE) else {"items": []}
    left = []
    for name in q.get("items", []):
        r = subprocess.run([sys.executable, os.path.join(HERE, "store_upload.py"), "--publish", name],
                           cwd=HERE, capture_output=True, text=True, encoding="utf-8")
        out = (r.stdout + r.stderr).strip()
        if "upload: SUCCESS" in out or "upload: IN_PROGRESS" in out:
            log("%s: UPLOADED + submitted - %s" % (name, " | ".join(l.strip() for l in out.splitlines())))
        elif "ITEM_NOT_UPDATABLE" in out:
            log("%s: still in review - queued" % name)
            left.append(name)
        else:
            log("%s: FAILED (kept queued) - %s" % (name, out[-400:].replace("\n", " | ")))
            left.append(name)
    q["items"] = left
    json.dump(q, open(QUEUE, "w", encoding="utf-8"), indent=1)
    if not left:
        r = subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True, text=True)
        log("queue empty - scheduled task removed (%s)" % (r.stdout.strip() or r.stderr.strip()))


if __name__ == "__main__":
    main()
