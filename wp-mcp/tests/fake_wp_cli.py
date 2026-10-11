#!/usr/bin/env python3
"""WP-CLI palsu: mencatat argumen ke $FAKE_WP_LOG dan memberi keluaran yang masuk akal."""

import os
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--path=") and a != "--no-color"]
log = os.environ.get("FAKE_WP_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\n")

joined = " ".join(args)
if joined.startswith("core version"):
    print("6.8.1")
elif joined.startswith("plugin list"):
    print("litespeed-cache\nwordfence\nwp-mcp-bridge")
elif joined.startswith("theme list"):
    print("twentytwentyfive")
else:
    print("Success: ok")
