"""Closed schemas and validation for managed animation authoring and inspection."""
import re
from validation import keys, integer, text
from motion import number, point, validate_tracks

NEW_ACTIONS = {'inspectAnimation', 'inspectGraph', 'authorScene', 'applyPoses', 'saveProject', 'setAudio'}
MUTATIONS = {'authorScene', 'applyPoses', 'saveProject', 'setAudio'}
RUN = {'type': 'string', 'pattern': '^run-[0-9a-f]{32}$'}
FRAME = {'type': 'integer', 'minimum': 0, 'maximum': 9999}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 128}
NUM = {'type': 'number', 'minimum': -100000, 'maximum': 100000}

def obj(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}

def array(item, minimum=0, maximum=16):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum}

POINT = obj({'x': NUM, 'y': NUM}, ['x', 'y'])
VALUES = obj({**{k: NUM for k in ('x', 'y', 'rotation', 'scaleX', 'scaleY', 'alpha')}, 'firstFrame': FRAME}, [])
KEY = obj({'frame': FRAME, 'values': VALUES, 'interpolation': {'enum': ['interpolate', 'hold']},
    'easing': {'oneOf': [{'enum': ['linear', 'ease_in', 'ease_out', 'ease_in_out', 'back_out', 'bounce_out']}, array({'type': 'number'}, 4, 4)]},
    'path': array(POINT, 2, 2)}, ['frame', 'values'])
TRACK = obj({'layer': NAME, 'instance': NAME, 'keys': array(KEY, 1, 64), 'pivot': POINT,
    'parent': {'type': 'integer', 'minimum': 0, 'maximum': 14}, 'rotation_mode': {'enum': ['explicit', 'shortest']}, 'playback': {'enum':['single frame','play once','loop']}, 'sync_to_timeline': {'type':'boolean'}}, ['layer', 'instance', 'keys'])
TRACKS = array(TRACK, 1, 16)
SCOPE = {'document_id': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647}, 'project_run_id': RUN, 'timeline_index': FRAME}
EDIT = {**SCOPE, 'revision_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'}}
# Each primitive type is validated again before it reaches the host.
PRIMITIVE = obj({'type': {'enum': ['rect', 'ellipse', 'path', 'text']}, 'bounds': obj({k: NUM for k in ('left', 'top', 'right', 'bottom')}, ['left', 'top', 'right', 'bottom']),
    'fill': {'type': ['string', 'null']}, 'stroke': {'type': ['string', 'null']}, 'stroke_width': {'type': 'number', 'minimum': 0, 'maximum': 32},
    'commands': array(array({'type': ['string', 'number']}, 1, 7), 1, 256), 'text': {'type': 'string', 'maxLength': 1024},
    'font_size': {'type': 'integer', 'minimum': 6, 'maximum': 160}, 'bold': {'type': 'boolean'}}, ['type'])
SYMBOL = obj({'name': NAME, 'frames': array(array(PRIMITIVE, 1, 128), 1, 24)}, ['name', 'frames'])
INSTANCE = obj({'layer': NAME, 'name': NAME, 'symbol': NAME, 'x': NUM, 'y': NUM, 'rotation': NUM,
    'scaleX': NUM, 'scaleY': NUM, 'alpha': {'type': 'number', 'minimum': 0, 'maximum': 100}, 'firstFrame': FRAME,
    'pivot': POINT, 'playback':{'enum':['single frame','play once','loop']}}, ['layer', 'name', 'symbol', 'x', 'y'])

TOOLS = [
    ('get_animation_state', 'Read complete scoped authoring keyframes: affine matrices, local pivots, alpha, graphic poses, spans, sound cues and symbol metadata. Returns a single-use revision for guarded edits. Values describe authoring keys, not renderer interpolation; confirm PNGs. Managed projects only.', obj({**SCOPE, 'layers': array(NAME, 0, 8), 'start_frame': FRAME, 'end_frame': FRAME, 'symbol_name': NAME}, list(SCOPE))),
    ('get_symbol_graph', 'Read bounded symbol dependencies, nested timelines and runtime MovieClip warnings. Managed project only; does not enter symbol editing.', obj(SCOPE, list(SCOPE))),
    ('plan_motion', 'Dry-run precise sampled animation: holds, custom cubic timing curves, overshoot/bounce, cubic spatial arcs, explicit/shortest rotations, local pivots and parent affine transforms. No Animate or filesystem access. At most 400 poses; split long spans.', obj({'tracks': TRACKS, 'step': {'type': 'integer', 'minimum': 1, 'maximum': 12}, 'include_poses': {'type': 'boolean'}}, ['tracks'])),
    ('apply_motion', 'Bake a planned motion into exact keyframes on named instances, including nested graphic timelines. Requires a fresh get_animation_state revision covering all affected frames/layers, managed project path and a backup. Never retries edits; validates readback matrices. Keys are sampled, not native tween approximations.', obj({**EDIT, 'tracks': TRACKS, 'step': {'type': 'integer', 'minimum': 1, 'maximum': 12}}, list(EDIT)+['tracks'])),
    ('retime_motion', 'Dry-run rescale a set of motion keys to a new frame range without touching Animate. Rejects collapsed key timings; preserves curves, pivots and parent relationships.', obj({'tracks': TRACKS, 'new_start': FRAME, 'new_end': FRAME}, ['tracks', 'new_start', 'new_end'])),
    ('solve_two_bone_ik', 'Pure planar two-bone IK: elbow position, world/local rotations, reachable flag and achieved-target error. No native bone rig or joint-limit solver is implied.', obj({'base': POINT, 'target': POINT, 'upper_length': {'type': 'number', 'minimum': .01, 'maximum': 10000}, 'lower_length': {'type': 'number', 'minimum': .01, 'maximum': 10000}, 'bend': {'enum': [-1, 1]}}, ['base', 'target', 'upper_length', 'lower_length'])),
    ('author_scene', 'Create new editable vector graphic symbols (including pose/viseme frames), place named parts on new unique layers, and extend a managed timeline. Native rectangles, ellipses, Bezier paths and text only; no SVG, scripts, external references or replacements. Guarded revision and backup required.', obj({**EDIT, 'frame_count': {'type': 'integer', 'minimum': 1, 'maximum': 10000}, 'symbols': array(SYMBOL, 0, 8), 'instances': array(INSTANCE, 0, 16)}, list(EDIT)+['frame_count', 'symbols', 'instances'])),
    ('save_project', 'Save only the matching MCP-created FLA after a revision check and nonempty backup. Never accepts an arbitrary save path.', obj(EDIT, list(EDIT))),
    ('begin_audio_upload', 'Create a new private upload job for a bounded PCM WAV. No source path or URL is accepted. Finalized uploads can be attached to managed timelines.', obj({'total_bytes': {'type': 'integer', 'minimum': 44, 'maximum': 16777216}}, ['total_bytes'])),
    ('append_audio_chunk', 'Append a base64 WAV chunk only at the expected byte offset in a private upload. At most 49152 decoded bytes per call; no overwrites or arbitrary paths.', obj({'run_id': RUN, 'offset': {'type': 'integer', 'minimum': 0, 'maximum': 16777216}, 'data_base64': {'type': 'string', 'maxLength': 65536}}, ['run_id', 'offset', 'data_base64'])),
    ('finish_audio_upload', 'Validate a completed PCM WAV: <=60 seconds, 8/16/24/32-bit integer PCM, mono/stereo, bounded sample rate. No decoder, plugin, network or executable is run.', obj({'run_id': RUN}, ['run_id'])),
    ('set_audio', 'Import a finalized private PCM WAV into a NEW uniquely named stream-sound layer at an exact frame, backed up and guarded by the inspected revision. Recorded cues can be mixed into a movie preview.', obj({**EDIT, 'audio_run_id': RUN, 'layer': NAME, 'start_frame': FRAME}, list(EDIT)+['audio_run_id', 'layer', 'start_frame'])),
    ('export_movie', 'Render up to 1440 root-timeline PNGs in bounded batches and create a full-length MP4/HTML preview, optionally mixing only the recorded managed PCM cues. Requires configured FFmpeg. Does not execute ActionScript or independently timed MovieClips.', obj({**SCOPE, 'start_frame': FRAME, 'end_frame': FRAME, 'audio': {'type': 'boolean'}}, list(SCOPE)+['start_frame', 'end_frame'])),
    ('review_frames', 'Inspect exported PNGs for repeated images, invalid/empty alpha and per-frame change metrics. Returns contact-sheet HTML and warnings, not an artistic quality score. Original renders remain unchanged.', obj({'run_id': RUN, 'indices': array({'type': 'integer', 'minimum': 0, 'maximum': 1439}, 1, 24)}, ['run_id', 'indices'])),
]
TOOL_DEFINITIONS = [{'name': name, 'description': description, 'inputSchema': schema} for name, description, schema in TOOLS]

def identity(value):
    text(value, 128)
    if any(c in value for c in ('/', '\\')) or value in ('.', '..') or any(ord(c)<32 for c in value):
        raise ValueError('Invalid timeline identity')


def validate_scope(options):
    integer(options['document_id'], 0, 2147483647); integer(options['timeline_index'], 0, 9999)
    if not isinstance(options['project_run_id'], str) or not re.fullmatch('run-[0-9a-f]{32}', options['project_run_id']):
        raise ValueError('Invalid managed project identifier')


def validate_art(symbols, instances):
    if not isinstance(symbols, list) or len(symbols)>8 or not isinstance(instances, list) or len(instances)>16:
        raise ValueError('Authoring batch exceeds bounds')
    if not symbols and not instances: raise ValueError('Empty authoring batch')
    names = set(); total = 0
    for symbol in symbols:
        keys(symbol, ('name', 'frames')); identity(symbol['name'])
        if symbol['name'] in names: raise ValueError('Duplicate symbol name')
        names.add(symbol['name'])
        frames = symbol['frames']
        if not isinstance(frames, list) or not 1 <= len(frames) <= 24: raise ValueError('Invalid symbol frames')
        for drawings in frames:
            if not isinstance(drawings, list) or not 1 <= len(drawings) <= 128: raise ValueError('Invalid drawing count')
            total += len(drawings)
            if total > 1024: raise ValueError('Authoring geometry exceeds bounds')
            for primitive in drawings:
                kind = primitive.get('type') if isinstance(primitive, dict) else None
                optional = ('fill', 'stroke', 'stroke_width')
                if kind == 'path':
                    keys(primitive, ('type', 'commands'), optional)
                    commands = primitive['commands']
                    if not isinstance(commands, list) or not 1 <= len(commands) <= 256: raise ValueError('Invalid path')
                    if not isinstance(commands[0],list) or not commands[0] or commands[0][0] != 'M': raise ValueError('Path must start with M')
                    for command in commands:
                        if not isinstance(command, list) or not command or command[0] not in {'M', 'L', 'Q', 'C', 'Z'}:
                            raise ValueError('Unsupported path operation')
                        if len(command) != {'M':3,'L':3,'Q':5,'C':7,'Z':1}[command[0]]: raise ValueError('Invalid path coordinates')
                        for coordinate in command[1:]: number(coordinate, -10000, 10000)
                elif kind in ('rect', 'ellipse', 'text'):
                    keys(primitive, ('type', 'bounds') + (('text', 'font_size', 'bold') if kind == 'text' else ()), optional)
                    b = primitive['bounds']; keys(b, ('left', 'top', 'right', 'bottom'))
                    for value in b.values(): number(value, -10000, 10000)
                    if b['right'] <= b['left'] or b['bottom'] <= b['top']: raise ValueError('Empty bounds')
                    if kind == 'text': text(primitive['text'],1024); integer(primitive['font_size'],6,160); assert_boolean(primitive['bold'])
                else: raise ValueError('Unsupported drawing primitive')
                for attribute in ('fill', 'stroke'):
                    value = primitive.get(attribute)
                    if value is not None and (not isinstance(value,str) or not re.fullmatch('#[0-9a-fA-F]{6}',value)):
                        raise ValueError('Only solid RGB colors are accepted')
                number(primitive.get('stroke_width', 1), 0, 32)
                if primitive.get('fill') is None and primitive.get('stroke') is None: raise ValueError('Invisible primitive')
    layers = set(); instance_names = set()
    for instance in instances:
        keys(instance, ('layer','name','symbol','x','y'), ('rotation','scaleX','scaleY','alpha','firstFrame','pivot','playback'))
        for name in ('layer','name','symbol'): identity(instance[name])
        if instance['layer'] in layers or instance['name'] in instance_names: raise ValueError('Duplicate placement identity')
        layers.add(instance['layer']); instance_names.add(instance['name'])
        for name in ('x','y','rotation'): number(instance.get(name, 0))
        for name in ('scaleX','scaleY'): number(instance.get(name, 1), -100, 100)
        number(instance.get('alpha', 100), 0, 100); integer(instance.get('firstFrame',0),0,9999)
        if 'pivot' in instance: point(instance['pivot'])
        if instance.get('playback','single frame') not in ('single frame','play once','loop'): raise ValueError('Invalid graphic playback')


def assert_boolean(value):
    if type(value) is not bool: raise ValueError('Boolean required')


def validate_new(action, options):
    required = {'inspectAnimation': list(SCOPE)+['layers','start_frame','end_frame','symbol_name'], 'inspectGraph': list(SCOPE),
        'authorScene': list(EDIT)+['frame_count','symbols','instances'], 'applyPoses': list(EDIT)+['poses'],
        'saveProject': list(EDIT), 'setAudio': list(EDIT)+['audio_run_id','layer','start_frame']}[action]
    keys(options, required); validate_scope(options)
    if action in MUTATIONS:
        if not isinstance(options['revision_id'],str) or not re.fullmatch('[0-9a-f]{32}',options['revision_id']): raise ValueError('Invalid inspection revision')
    if action == 'inspectAnimation':
        layers=options['layers']
        if not isinstance(layers,list) or len(layers)>8: raise ValueError('Invalid inspection layers')
        for layer in layers: identity(layer)
        if len(set(layers))!=len(layers): raise ValueError('Duplicate inspection layers')
        start=integer(options['start_frame'],0,9999); integer(options['end_frame'],start,min(9999,start+239))
        if options['symbol_name'] is not None: identity(options['symbol_name'])
    elif action == 'authorScene':
        integer(options['frame_count'],1,10000); validate_art(options['symbols'],options['instances'])
    elif action == 'applyPoses':
        poses=options['poses']
        if not isinstance(poses,list) or not 1<=len(poses)<=400: raise ValueError('Invalid pose count')
        seen=set()
        for pose in poses:
            keys(pose, ('layer','instance','frame','matrix','alpha','firstFrame'), ('loop',))
            identity(pose['layer']); identity(pose['instance']); integer(pose['frame'],0,9999)
            target=(pose['layer'],pose['instance'],pose['frame'])
            if target in seen: raise ValueError('Duplicate baked pose')
            seen.add(target); keys(pose['matrix'], ('a','b','c','d','tx','ty'))
            for value in pose['matrix'].values(): number(value, -10000000, 10000000)
            number(pose['alpha'],0,100); integer(pose['firstFrame'],0,9999)
            if pose.get('loop','single frame') not in ('single frame','play once','loop'): raise ValueError('Invalid graphic playback')
    elif action == 'setAudio':
        if not isinstance(options['audio_run_id'],str) or not re.fullmatch('run-[0-9a-f]{32}',options['audio_run_id']): raise ValueError('Invalid audio identifier')
        identity(options['layer']); integer(options['start_frame'],0,9999)
