"""Stage ONLY the ?v= cache-bust tags for the given data files in index.html.

The scheduled refresh scripts bump `<file>?v=` in the working-tree index.html,
but other Claude sessions often have unrelated uncommitted edits in that same
file. This builds the staged index.html from HEAD's copy with just those tags
swapped to the working tree's values, so a scheduled commit never sweeps up
(or gets blocked by) another session's work. The working tree is untouched.

usage: python scripts/stage_vbump.py data/combine_data.js data/draft_proj.js ...
Prints the tags it staged; exit 0 even when nothing changed.
"""
import os
import re
import subprocess
import sys

INDEX = "index.html"


def main(paths):
    with open(INDEX, "rb") as f:
        work = f.read().decode("utf-8")
    head = subprocess.run(["git", "show", "HEAD:" + INDEX], capture_output=True, check=True).stdout.decode("utf-8")
    staged = head
    for p in paths:
        name = os.path.basename(p)
        pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(name))
        new_vers = [m.group(2) for m in pat.finditer(work)]
        if not new_vers:
            continue
        it = iter(new_vers)
        # Same tag count in both copies -> swap in order; otherwise use the first working value for all.
        same = len(new_vers) == len(pat.findall(head))
        staged = pat.sub(lambda m: m.group(1) + (next(it) if same else new_vers[0]), staged)
    if staged == head:
        print("stage_vbump: no ?v= changes")
        return 0
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=staged.encode("utf-8"),
                          capture_output=True, check=True).stdout.decode().strip()
    mode = subprocess.run(["git", "ls-files", "-s", "--", INDEX], capture_output=True, check=True).stdout.decode().split()[0]
    subprocess.run(["git", "update-index", "--cacheinfo", "%s,%s,%s" % (mode, blob, INDEX)], check=True)
    print("stage_vbump: staged ?v= bumps for " + ", ".join(os.path.basename(p) for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
