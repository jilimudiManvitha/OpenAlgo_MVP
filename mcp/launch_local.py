"""Local MCP launcher that keeps the application API key out of process arguments.

Usage: python mcp/launch_local.py --api-key-file /private/path/key --host URL
The file contains only the OpenAlgo application API key (not a broker token).
"""

import argparse
import os
import runpy
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--host", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    key = args.api_key_file.read_text().strip()
    if not key or len(key) > 256 or any(char.isspace() for char in key):
        parser.error("API key file is empty or invalid")
    # This is a stdio process even if its parent happens to have HTTP boot set.
    os.environ.pop("OPENALGO_MCP_HTTP_BOOT", None)
    target = Path(__file__).with_name("mcpserver.py")
    # Only the in-process argv contains the key; the OS command line never does.
    sys.argv = [str(target), key, args.host.rstrip("/")]
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
