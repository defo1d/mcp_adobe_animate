#!/usr/bin/env python3
"""Small stdio MCP adapter with no third-party runtime or installation hooks."""
import json
import re
import sys
import urllib.error
import urllib.request
from config import load_config, MAX_BODY
from preview import frame_content, encode_mp4
from validation import keys, validate_command
from auth import strict_json, request_headers, check_response
from animation_tools import TOOL_DEFINITIONS
from motion import compile_motion, retime_motion, solve_two_bone
from audio import begin, append, finalize
from review import export_movie, review


def obj(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}

INT = {'type': 'integer', 'minimum': 0, 'maximum': 9999}
DOC = {'type': 'integer', 'minimum': 0, 'maximum': 2147483647}
TOOLS = [
    {'name': 'create_project', 'description': 'Create and open a NEW FLA in a new private MCP directory. Never overwrites or edits an existing document. Optional built-in smoke_test template creates a 48-frame test actor.', 'inputSchema': obj({'width': {'type':'integer','minimum':16,'maximum':4096}, 'height': {'type':'integer','minimum':16,'maximum':4096}, 'frame_rate': {'type':'integer','minimum':1,'maximum':120}, 'background': {'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}, 'template': {'enum':['blank','smoke_test']}}, [])},
    {'name': 'open_project', 'description': 'Open only an FLA previously created by this MCP, identified by its generated run_id. No arbitrary file path accepted.', 'inputSchema': obj({'run_id': {'type':'string','pattern':'^run-[0-9a-f]{32}$'}}, ['run_id'])},
    {'name': 'get_documents', 'description': 'List open Animate documents and stable document IDs for this app session.', 'inputSchema': obj({}, [])},
    {'name': 'get_timeline', 'description': 'Inspect layers and keyframe element names of a pinned document/current editing timeline.', 'inputSchema': obj({'document_id': DOC}, ['document_id'])},
    {'name': 'get_library', 'description': 'Inspect library symbols of a pinned document. Returns items, total_items and an explicit truncated flag for large results.', 'inputSchema': obj({'document_id': DOC}, ['document_id'])},
    {'name': 'export_frames', 'description': 'Export up to 240 timeline PNGs into a new private directory and make a local HTML player. Zero-based inclusive frame range; runtime MovieClips/ActionScript/audio are not simulated.', 'inputSchema': obj({'document_id': DOC, 'timeline_index': INT, 'start_frame': INT, 'end_frame': INT, 'step': {'type': 'integer', 'minimum': 1, 'maximum': 120}}, ['document_id', 'timeline_index', 'start_frame', 'end_frame'])},
    {'name': 'create_preview', 'description': 'Export frames and HTML playback; optionally encode a silent MP4 using the locally configured ffmpeg. No executable paths accepted.', 'inputSchema': obj({'document_id': DOC, 'timeline_index': INT, 'start_frame': INT, 'end_frame': INT, 'step': {'type': 'integer', 'minimum': 1, 'maximum': 120}, 'mp4': {'type': 'boolean'}}, ['document_id', 'timeline_index', 'start_frame', 'end_frame'])},
    {'name': 'get_frame', 'description': 'Return one exported PNG as an MCP image for visual inspection. Frame index is zero-based within the export.', 'inputSchema': obj({'run_id': {'type': 'string', 'pattern': '^run-[0-9a-f]{32}$'}, 'index': {'type': 'integer', 'minimum': 0, 'maximum': 239}}, ['run_id', 'index'])},
    {'name': 'export_sprite_sheet', 'description': 'Export a library symbol as PNG+JSON to a new private directory. No output path accepted.', 'inputSchema': obj({'document_id': DOC, 'symbol_name': {'type': 'string', 'maxLength': 256}, 'max_width': {'type': 'integer', 'minimum': 16, 'maximum': 4096}, 'max_height': {'type': 'integer', 'minimum': 16, 'maximum': 4096}, 'padding': {'type': 'integer', 'minimum': 0, 'maximum': 32}}, ['document_id', 'symbol_name'])},
    {'name': 'export_all_sprite_sheets', 'description': 'Export at most 64 graphic/movie clip library symbols into generated filenames.', 'inputSchema': obj({'document_id': DOC}, ['document_id'])},
    {'name': 'apply_animation', 'description': 'Back up the pinned FLA into a new export directory, then apply bounded poses/keyframes and classic tweens to named symbol instances. Requires the pinned root scene; exit symbol editing first. Zero-based frame/layer indices. No arbitrary code.', 'inputSchema': obj({'document_id': DOC, 'timeline_index': INT, 'operations': {'type': 'array', 'minItems': 1, 'maxItems': 200, 'items': {'oneOf': [obj({'type': {'const': 'pose'}, 'layer': {'type': 'integer', 'minimum': 0, 'maximum': 199}, 'frame': INT, 'instance': {'type': 'string', 'maxLength': 128}, 'values': obj({'x': {'type': 'number'}, 'y': {'type': 'number'}, 'rotation': {'type': 'number'}, 'scaleX': {'type': 'number'}, 'scaleY': {'type': 'number'}, 'alpha': {'type': 'number', 'minimum': 0, 'maximum': 100}, 'firstFrame': INT, 'loop': {'enum': ['loop', 'play once', 'single frame']}}, [])}, ['type', 'layer', 'frame', 'instance', 'values']), obj({'type': {'const': 'classic_tween'}, 'layer': {'type': 'integer', 'minimum': 0, 'maximum': 199}, 'start_frame': INT, 'end_frame': INT, 'easing': {'type': 'integer', 'minimum': -100, 'maximum': 100}}, ['type', 'layer', 'start_frame', 'end_frame', 'easing'])]}}}, ['document_id', 'timeline_index', 'operations'])},
    {'name': 'execute_extend_script', 'description': 'DISABLED by default. Requires local allow_scripts=true AND manual approval of this exact script in the Animate panel. JSFL has access to files and is not sandboxed.', 'inputSchema': obj({'document_id': DOC, 'script': {'type': 'string', 'maxLength': 32768}}, ['document_id', 'script'])},
]
TOOLS.extend(TOOL_DEFINITIONS)
next(v for v in TOOLS if v['name']=='get_frame')['inputSchema']['properties']['index']['maximum'] = 1439
SCHEMAS = {v['name']: v['inputSchema'] for v in TOOLS}
ACTIONS = {'create_project': 'createProject', 'open_project': 'openProject', 'get_documents': 'getDocuments', 'get_timeline': 'getTimeline', 'get_library': 'getLibrary',
           'export_frames': 'exportFrames', 'export_sprite_sheet': 'exportSpriteSheet',
           'export_all_sprite_sheets': 'exportAllSpriteSheets', 'apply_animation': 'applyAnimation',
           'execute_extend_script': 'executeExtendScript'}
ACTIONS.update({'get_animation_state':'inspectAnimation', 'get_symbol_graph':'inspectGraph',
                'author_scene':'authorScene', 'save_project':'saveProject', 'set_audio':'setAudio'})


def exchange(config, path, value, instance='hello'):
    data = json.dumps(value, allow_nan=False).encode()
    if len(data) > MAX_BODY:
        raise ValueError('Command too large')
    url = 'http://127.0.0.1:' + str(config['port']) + path
    headers = request_headers(config['client_token'], '127.0.0.1:' + str(config['port']), path, data, instance=instance)
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', **headers})
    # Do not send credentials to proxies configured in the user's environment; no redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(req, timeout=125)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(MAX_BODY + 1)
        status = response.status
        signature = response.headers.get('X-Animate-Signature')
    if len(raw) > MAX_BODY:
        raise ValueError('Bridge response too large')
    check_response(config['client_token'], headers['X-Animate-Nonce'], status, raw, signature)
    result = strict_json(raw)
    if status != 200 or not result.get('ok'):
        raise ValueError(str(result.get('error', 'Bridge failed'))[:1024])
    return result['data']


def request(config, action, options):
    validate_command(action, options, config['allow_scripts'])
    hello = exchange(config, '/v1/hello', {})
    instance = hello.get('instance') if isinstance(hello, dict) else None
    if not isinstance(instance, str) or not re.fullmatch('[0-9a-f]{32}', instance):
        raise ValueError('Invalid authenticated server identity')
    return exchange(config, '/v1/command', {'action': action, 'options': options}, instance)


def call_tool(config, name, args):
    if name=='apply_animation':raise ValueError('Legacy unguarded edits are retired; use get_animation_state and apply_motion on a managed project')
    if name not in SCHEMAS:
        raise ValueError('Unknown tool')
    schema = SCHEMAS[name]
    keys(args, schema['required'], set(schema['properties']) - set(schema['required']))
    args = dict(args)
    if name == 'create_project':
        for key,value in {'width':640,'height':360,'frame_rate':24,'background':'#F4F0E7','template':'blank'}.items():
            args.setdefault(key,value)
    if name in ('export_frames', 'create_preview'):
        args.setdefault('step', 1)
    if name == 'get_frame':
        return {'content': [frame_content(config, args['run_id'], args['index'])], 'isError': False}
    if name == 'get_animation_state':
        for key,value in {'layers':[], 'start_frame':0, 'end_frame':0, 'symbol_name':None}.items(): args.setdefault(key,value)
    if name in ('plan_motion','apply_motion'):
        step=args.get('step',2)
        result=compile_motion(args['tracks'],step)
        if name=='plan_motion':
            include=args.get('include_poses',False)
            if type(include) is not bool: raise ValueError('include_poses must be boolean')
            if not include: result.pop('poses')
        else:
            command={k:args[k] for k in ('document_id','project_run_id','timeline_index','revision_id')}
            result=request(config,'applyPoses',{**command,'poses':result['poses']})
    elif name=='retime_motion':
        result=retime_motion(args['tracks'],args['new_start'],args['new_end'])
    elif name=='solve_two_bone_ik':
        result=solve_two_bone(args['base'],args['target'],args['upper_length'],args['lower_length'],args.get('bend',1))
    elif name=='begin_audio_upload': result=begin(config,args['total_bytes'])
    elif name=='append_audio_chunk': result=append(config,args['run_id'],args['offset'],args['data_base64'])
    elif name=='finish_audio_upload': result=finalize(config,args['run_id'])
    elif name=='review_frames': result=review(config,args['run_id'],args['indices'])
    elif name=='export_movie': result=export_movie(config,args,request)
    elif name == 'create_preview':
        mp4 = args.pop('mp4', False)
        if type(mp4) is not bool:
            raise ValueError('mp4 must be boolean')
        if mp4 and not config['ffmpeg_path']:
            raise ValueError('Configure an existing ffmpeg explicitly before requesting MP4')
        result = request(config, 'exportFrames', args)
        if mp4:
            result.update(encode_mp4(config, result['run_id']))
    else:
        if name == 'export_sprite_sheet':
            for key, value in {'max_width': 2048, 'max_height': 2048, 'padding': 2}.items():
                args.setdefault(key, value)
        result = request(config, ACTIONS[name], args)
    return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=True, allow_nan=False)}], 'isError': False}


class Protocol:
    def __init__(self, config):
        self.config = config
        self.initialized = False

    def handle(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in message:
            return None  # Notifications must not produce stdout responses.
        request_id = message['id']
        if type(request_id) not in (str, int):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid ID'}}
        method = message.get('method')
        params = message.get('params', {})
        try:
            if method == 'initialize':
                if not isinstance(params, dict):
                    raise ValueError('Invalid initialization')
                version = params.get('protocolVersion')
                supported = ('2024-11-05', '2025-03-26', '2025-06-18')
                self.initialized = True
                result = {'protocolVersion': version if version in supported else supported[-1],
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'animate-mcp-safe', 'version': '1.3.0'},
                          'instructions': 'Use managed project IDs. Inspect scoped animation with get_animation_state, plan exact motion, then apply with its fresh single-use revision. Every guarded edit makes a backup and apply_motion verifies native matrices. Inspect rendered PNGs with get_frame/review_frames; export_movie renders longer scenes and recorded PCM cues. Never blindly retry edits after errors. Authoring values do not prove rendered appearance; runtime MovieClips/ActionScript are not simulated. General JSFL is disabled.'}
            elif method == 'ping':
                result = {}
            elif not self.initialized:
                raise ValueError('Initialize first')
            elif method == 'tools/list':
                result = {'tools': [tool for tool in TOOLS if tool['name']!='apply_animation' and (self.config['allow_scripts'] or tool['name']!='execute_extend_script')]}
            elif method == 'tools/call':
                keys(params, ('name',), ('arguments', '_meta'))
                try:
                    result = call_tool(self.config, params['name'], params.get('arguments', {}))
                except Exception as error:
                    result = {'content': [{'type': 'text', 'text': str(error)[:1024]}], 'isError': True}
            else:
                return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Method not supported'}}
            return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except (ValueError, TypeError, KeyError) as error:
            return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32602, 'message': str(error)[:1024]}}


def main():
    protocol = Protocol(load_config())
    while True:
        line = sys.stdin.buffer.readline(MAX_BODY + 1)
        if not line:
            return
        if len(line) > MAX_BODY:
            # Fail closed; do not continue parsing trailing chunks of an oversized request.
            raise SystemExit('MCP message exceeds size limit')
        try:
            message = strict_json(line)
            response = protocol.handle(message)
        except (ValueError, RecursionError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)

if __name__ == '__main__':
    main()
