"""Local configuration. Never supplied by MCP tool arguments."""
import os
from pathlib import Path
import re
import stat
from auth import strict_json

MAX_BODY = 131072
MAX_FRAMES = 240
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 256 * 1024 * 1024
ACTIONS = frozenset({"createProject", "openProject", "getDocuments", "getTimeline", "getLibrary", "exportFrames",
    "exportSpriteSheet", "exportAllSpriteSheets", "applyAnimation", "executeExtendScript"})


def load_config(filename=None):
    name = filename or os.environ.get("ANIMATE_MCP_CONFIG")
    if not name or not Path(name).is_absolute():
        raise ValueError("Set ANIMATE_MCP_CONFIG to an absolute private configuration file")
    path = Path(name)
    if path.is_symlink():
        raise ValueError("Configuration must not be a symlink")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Configuration must be owned by you with mode 600")
        raw = stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("Configuration too large")
    data = strict_json(raw)
    if set(data) != {"client_token", "panel_token", "output_dir", "port", "allow_scripts", "ffmpeg_path"}:
        raise ValueError("Unexpected configuration fields")
    for key in ("client_token", "panel_token"):
        if not isinstance(data[key], str) or not re.fullmatch(r"[0-9a-f]{64}", data[key]):
            raise ValueError("Invalid pairing token")
    if data["client_token"] == data["panel_token"]:
        raise ValueError("Client and panel credentials must be different")
    if type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
        raise ValueError("Invalid port")
    if type(data["allow_scripts"]) is not bool:
        raise ValueError("allow_scripts must be boolean")
    root = Path(data["output_dir"])
    if not root.is_absolute() or root == Path('/'):
        raise ValueError("output_dir must be an absolute dedicated directory")
    # Reject symlinks anywhere in the configured export root.
    for part in (root, *root.parents):
        if part.is_symlink():
            raise ValueError("Export root must not contain symlinks")
    data["output_dir"] = root
    exe = data["ffmpeg_path"]
    if exe is not None:
        if not isinstance(exe, str) or not Path(exe).is_absolute():
            raise ValueError("ffmpeg_path must be an explicit absolute path or null")
        resolved = Path(exe).resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError("Configured ffmpeg is not executable")
        data["ffmpeg_path"] = str(resolved)
    return data


def prepare_root(config):
    root = config["output_dir"]
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("Export directory must be owned by you with mode 700")
    return root
