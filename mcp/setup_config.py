"""Explicit, optional setup; does not install Adobe extensions or change preferences."""
import argparse
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", type=int, default=3099)
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args()
    if not args.config.is_absolute() or not args.output.is_absolute():
        parser.error("Use absolute paths")
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid port")
    data = {"client_token": secrets.token_hex(32), "panel_token": secrets.token_hex(32),
            "output_dir": str(args.output), "port": args.port, "allow_scripts": False,
            "ffmpeg_path": args.ffmpeg}
    # No overwrite of an existing configuration, and no secret in stdout.
    fd = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    print("Private configuration created. No extension installed.")

if __name__ == "__main__":
    main()
