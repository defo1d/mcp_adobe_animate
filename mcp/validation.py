"""Enforce the same closed command schema before queueing any host operation."""
import math
import re
from config import ACTIONS, MAX_FRAMES


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Integer outside allowed range")
    return value


def text(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum or '\x00' in value:
        raise ValueError("Invalid text value")
    return value


def keys(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or not set(required) <= set(obj):
        raise ValueError("Invalid or unexpected fields")


def validate_command(action, options, allow_scripts=False):
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("Unsupported action")
    if action in {"inspectAnimation", "inspectGraph", "authorScene", "applyPoses", "saveProject", "setAudio"}:
        from animation_tools import validate_new
        validate_new(action, options)
        return
    if action == "getDocuments":
        keys(options, ())
        return
    if action == "createProject":
        keys(options, ("width", "height", "frame_rate", "background", "template"))
        integer(options['width'], 16, 4096)
        integer(options['height'], 16, 4096)
        integer(options['frame_rate'], 1, 120)
        if not isinstance(options['background'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',options['background']):
            raise ValueError('Invalid background color')
        if options['template'] not in ('blank','smoke_test'):
            raise ValueError('Unknown project template')
        if options['template']=='smoke_test' and (options['width'],options['height'])!=(640,360):
            raise ValueError('Smoke test template requires 640 x 360')
        return
    if action == "openProject":
        keys(options, ("run_id",))
        if not isinstance(options['run_id'],str) or not re.fullmatch('run-[0-9a-f]{32}',options['run_id']):
            raise ValueError('Invalid project identifier')
        return
    if action in {"getTimeline", "getLibrary"}:
        keys(options, ("document_id",))
    elif action in {"exportFrames", "exportManagedFrames"}:
        keys(options, ("document_id", "timeline_index", "start_frame", "end_frame", "step") + (("project_run_id",) if action == "exportManagedFrames" else ()))
        if action == "exportManagedFrames":
            from animation_tools import validate_scope
            validate_scope(options)
        integer(options['timeline_index'], 0, 9999)
        start = integer(options["start_frame"], 0, 9999)
        end = integer(options["end_frame"], start, 9999)
        step = integer(options["step"], 1, 120)
        if len(range(start, end + 1, step)) > MAX_FRAMES:
            raise ValueError("At most 240 frames per export")
    elif action == "exportSpriteSheet":
        keys(options, ("document_id", "symbol_name", "max_width", "max_height", "padding"))
        text(options["symbol_name"])
        integer(options["max_width"], 16, 4096)
        integer(options["max_height"], 16, 4096)
        integer(options["padding"], 0, 32)
    elif action == "exportAllSpriteSheets":
        keys(options, ("document_id",))
    elif action == "applyAnimation":
        keys(options, ("document_id", "timeline_index", "operations"))
        integer(options['timeline_index'], 0, 9999)
        ops = options["operations"]
        if not isinstance(ops, list) or not 1 <= len(ops) <= 200:
            raise ValueError("Supply 1 to 200 operations")
        for op in ops:
            if not isinstance(op, dict):
                raise ValueError("Invalid operation")
            if op.get("type") == "pose":
                keys(op, ("type", "layer", "frame", "instance", "values"))
                integer(op["layer"], 0, 199)
                integer(op["frame"], 0, 9999)
                text(op["instance"], 128)
                vals = op["values"]
                allowed = {"x", "y", "rotation", "scaleX", "scaleY", "alpha", "firstFrame", "loop"}
                if not isinstance(vals, dict) or not vals or set(vals) - allowed:
                    raise ValueError("Unsupported pose properties")
                for key, val in vals.items():
                    if key == "loop":
                        if val not in ("loop", "play once", "single frame"):
                            raise ValueError("Invalid graphic playback mode")
                    elif key == "firstFrame":
                        integer(val, 0, 9999)
                    else:
                        if type(val) not in (int, float) or not math.isfinite(val):
                            raise ValueError("Pose properties must be finite numbers")
                        low, high = {"alpha": (0, 100), "scaleX": (-100, 100), "scaleY": (-100, 100)}.get(key, (-100000, 100000))
                        if not low <= val <= high:
                            raise ValueError("Pose property outside allowed range")
            elif op.get("type") == "classic_tween":
                keys(op, ("type", "layer", "start_frame", "end_frame", "easing"))
                integer(op["layer"], 0, 199)
                start = integer(op["start_frame"], 0, 9998)
                integer(op["end_frame"], start + 1, 9999)
                integer(op["easing"], -100, 100)
            else:
                raise ValueError("Unsupported animation operation")
    elif action == "executeExtendScript":
        keys(options, ("document_id", "script"))
        if not allow_scripts:
            raise ValueError("Arbitrary JSFL is disabled by local configuration")
        text(options["script"], 32768)
    integer(options["document_id"], 0, 2147483647)
