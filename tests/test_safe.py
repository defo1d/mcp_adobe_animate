import concurrent.futures
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp'))
from auth import request_headers, check_response, strict_json
from config import load_config, prepare_root, MAX_BODY
from validation import validate_command
from bridge import Server, Broker, Pending
from preview import create_job, find_job, read_png, finish_frames, frame_content, encode_mp4, project_file
spec = importlib.util.spec_from_file_location('adapter', ROOT / 'mcp/an-mcp.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def png(width=16, height=16, color=(220, 80, 70, 255)):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    pixels = b''.join(b'\x00' + bytes(color) * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


class LocalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.filename = self.root / 'private.json'
        self.data = {'client_token': 'a' * 64, 'panel_token': 'b' * 64,
                     'output_dir': str(self.root / 'exports'), 'port': 3099,
                     'allow_scripts': False, 'ffmpeg_path': None}
        self.filename.write_text(json.dumps(self.data))
        self.filename.chmod(0o600)
        self.config = load_config(str(self.filename))
    def tearDown(self):
        self.temp.cleanup()


class ConfigurationTests(LocalTest):
    def test_private_config_and_root(self):
        root = prepare_root(self.config)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.filename.chmod(0o644)
        with self.assertRaises(ValueError): load_config(str(self.filename))
    def test_config_symlink_and_equal_tokens(self):
        link = self.root / 'link.json'; link.symlink_to(self.filename)
        with self.assertRaises(ValueError): load_config(str(link))
        self.data['panel_token'] = self.data['client_token']
        self.filename.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError): load_config(str(self.filename))
    def test_export_ancestor_symlink_and_shared_root(self):
        folder = self.root / 'real'; folder.mkdir(mode=0o700)
        link = self.root / 'linked'; link.symlink_to(folder, target_is_directory=True)
        self.data['output_dir'] = str(link / 'exports')
        self.filename.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError): load_config(str(self.filename))
        prepare_root(self.config).chmod(0o755)
        with self.assertRaises(ValueError): create_job(self.config)
    def test_setup_no_overwrite_or_stdout_secrets(self):
        args = [sys.executable, str(ROOT / 'mcp/setup_config.py'), '--config', str(self.root / 'new.json'), '--output', str(self.root / 'new exports')]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        cfg = load_config(str(self.root / 'new.json'))
        self.assertNotIn(cfg['panel_token'], result.stdout)
        self.assertEqual((self.root / 'new.json').stat().st_mode & 0o777, 0o600)
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(load_config(str(self.root / 'new.json')), cfg)


class ValidationTests(LocalTest):
    def test_projects_accept_no_paths_or_scripts(self):
        base={'width':640,'height':360,'frame_rate':24,'background':'#F4F0E7','template':'blank'}
        validate_command('createProject',base)
        validate_command('openProject',{'run_id':'run-'+'c'*32})
        for bad in [dict(base,output_uri='file:///tmp/'),dict(base,script='fl.injected=true;'),dict(base,background='";evil()'),dict(base,width=True),dict(base,template='../existing')]:
            with self.assertRaises(ValueError): validate_command('createProject',bad)
        for bad in [{'run_id':'../existing'},{'run_id':'run-'+'c'*32,'path':'/tmp/user.fla'}]:
            with self.assertRaises(ValueError): validate_command('openProject',bad)
    def test_legacy_injection_alias_paths_and_raw_code_rejected(self):
        for action, options in [('constructor', {}), ('__proto__', {}), (['getDocuments'], {}),
            ('getDocuments', {'script': 'FLfile.remove("file:///etc")'}),
            ('getTimeline', {'document_id': True}),
            ('exportFrames', {'document_id': 1, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 1, 'step': 1, 'output_uri': 'file:///etc/'}),
            ('executeExtendScript', {'document_id': 1, 'script': 'return FLfile.read("file:///etc/passwd");'})]:
            with self.subTest(action=action), self.assertRaises(ValueError): validate_command(action, options)
    def test_frame_resource_limits(self):
        base = {'document_id': 1, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 239, 'step': 1}
        validate_command('exportFrames', base)
        for key, value in [('end_frame', 240), ('step', 0), ('start_frame', -1), ('end_frame', float('inf'))]:
            with self.subTest(key=key), self.assertRaises(ValueError): validate_command('exportFrames', dict(base, **{key: value}))
    def test_declarative_pose_control_and_bad_properties(self):
        op = {'type': 'pose', 'layer': 0, 'frame': 2, 'instance': 'mouth', 'values': {'x': 3, 'firstFrame': 2, 'loop': 'single frame'}}
        validate_command('applyAnimation', {'document_id': 1, 'timeline_index': 0, 'operations': [op]})
        for values in [{'__proto__': {}}, {'x': float('nan')}, {'x': True}, {'alpha': 101}, {'loop': 'eval'}, {}, {'firstFrame': 0.5}]:
            with self.subTest(values=values), self.assertRaises(ValueError): validate_command('applyAnimation', {'document_id': 1, 'timeline_index': 0, 'operations': [dict(op, values=values)]})
    def test_zero_sprite_padding_and_literal_symbol(self):
        validate_command('exportSpriteSheet', {'document_id': 1, 'symbol_name': '\"); FLfile.remove(\"x\"); //\u2028', 'max_width': 16, 'max_height': 16, 'padding': 0})
        validate_command('executeExtendScript', {'document_id': 1, 'script': 'return 1;'}, True)


class ArtifactTests(LocalTest):
    def test_managed_project_requires_generated_record_and_rejects_symlinks(self):
        job=create_job(self.config)
        fla=job/'project.fla';fla.write_bytes(b'test FLA')
        with self.assertRaises(FileNotFoundError): project_file(self.config,job.name)
        (job/'project.json').write_text(json.dumps({'kind':'animate-mcp-project-v1','file':'project.fla'}))
        self.assertEqual(project_file(self.config,job.name),fla)
        fla.unlink();fla.symlink_to(self.filename)
        with self.assertRaises(ValueError): project_file(self.config,job.name)
        fla.unlink();fla.write_bytes(b'test FLA')
        (job/'project.json').unlink();(job/'project.json').symlink_to(self.filename)
        with self.assertRaises(OSError): project_file(self.config,job.name)
    def frames(self, count=3):
        job = create_job(self.config)
        for i in range(count): (job / ('frame-%06d.png' % (i + 1))).write_bytes(png(17, 15, (50 + i * 50, 90, 160, 255)))
        return job
    def test_preview_real_png_image_and_xss_escaping(self):
        job = self.frames()
        result = finish_frames(self.config, job, {'document_id': 1, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 4, 'step': 2}, {'frame_rate': 24, 'document_name': '</h1><script>alert(1)</script>'})
        self.assertEqual(result['playback_fps'], 12)
        self.assertEqual(result['frame_count'], 3)
        page = Path(result['preview_html']).read_text()
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn("connect-src 'none'", page)
        image = frame_content(self.config, job.name, 1)
        self.assertEqual(image['type'], 'image')
        self.assertEqual(image['mimeType'], 'image/png')
        self.assertTrue(image['data'].startswith('iVBOR'))
    def test_traversal_symlink_and_index_rejected(self):
        job = self.frames()
        for name in ['../', 'run-' + '0' * 32 + '/../../x', 'file:///etc', 'run-' + 'z' * 32]:
            with self.subTest(name=name), self.assertRaises(ValueError): find_job(self.config, name)
        for index in [-1, 1440, True, 0.5]:
            with self.subTest(index=index), self.assertRaises(ValueError): frame_content(self.config, job.name, index)
        (job / 'frame-000001.png').unlink(); (job / 'frame-000001.png').symlink_to(self.filename)
        with self.assertRaises(OSError): frame_content(self.config, job.name, 0)
        job2 = create_job(self.config); job2.rmdir(); job2.symlink_to(job, target_is_directory=True)
        with self.assertRaises(ValueError): find_job(self.config, job2.name)
    def test_png_dimensions_checksums_and_missing_file(self):
        path = self.root / 'bad.png'
        for content in [b'not PNG' * 20, png(4097, 1), png()[:-1], png()[:40] + b'BAD' + png()[43:]]:
            path.write_bytes(content)
            with self.subTest(size=len(content)), self.assertRaises(ValueError): read_png(path)
        job = self.frames(1)
        with self.assertRaises(FileNotFoundError): finish_frames(self.config, job, {'document_id': 1, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 1, 'step': 1}, {'frame_rate': 24})
    def test_optional_ffmpeg_real_encoding_odd_dimensions(self):
        exe = os.environ.get('ANIMATE_TEST_FFMPEG')
        if not exe: self.skipTest('Set ANIMATE_TEST_FFMPEG to an existing encoder; no installation required')
        self.config['ffmpeg_path'] = str(Path(exe).resolve(strict=True))
        job = self.frames()
        finish_frames(self.config, job, {'document_id': 1, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 2, 'step': 1}, {'frame_rate': 24})
        result = encode_mp4(self.config, job.name)
        self.assertGreater(Path(result['mp4']).stat().st_size, 100)
        self.assertIn(b'ftyp', Path(result['mp4']).read_bytes()[:32])
        self.assertFalse(result['audio'])


class HTTPFixture(LocalTest):
    def setUp(self):
        super().setUp()
        self.server = Server(self.config, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.port = self.server.server_port
        self.session = 'c' * 32
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        super().tearDown()
    def http(self, path, data, token=None, headers=None, method='POST'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        hdr = {'Content-Type': 'application/json'}
        if token: hdr.update(request_headers(token, '127.0.0.1:' + str(self.port), path, body, instance='hello' if path in ('/v1/hello', '/v1/panel/hello') else self.server.instance))
        hdr.update(headers or {})
        conn.request(method, path, body, hdr)
        response = conn.getresponse(); raw = response.read(); conn.close()
        return response.status, json.loads(raw) if raw else None
    def register(self):
        status, _ = self.http('/v1/panel/register', {'session': self.session}, self.config['panel_token'])
        self.assertEqual(status, 200)
class BridgeTests(HTTPFixture):
    def test_loopback_auth_and_role_separation(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for token in [None, 'f' * 64, self.config['client_token']]:
            self.assertEqual(self.http('/v1/panel/register', {'session': self.session}, token)[0], 401)
        self.register()
        self.assertEqual(self.http('/v1/command', {'action': 'getDocuments', 'options': {}}, self.config['panel_token'])[0], 401)
    def test_origin_dns_rebinding_and_preflight(self):
        for hdr in [{'Host': 'localhost:' + str(self.port)}, {'Host': 'evil.test:' + str(self.port)}, {'Origin': 'https://evil.test'}]:
            self.assertEqual(self.http('/v1/panel/register', {'session': self.session}, self.config['panel_token'], hdr)[0], 403)
        self.assertEqual(self.http('/v1/panel/register', {}, headers={'Origin': 'null', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'}, method='OPTIONS')[0], 204)
        self.assertEqual(self.http('/v1/panel/register', {}, headers={'Origin': 'https://evil.test', 'Access-Control-Request-Method': 'POST'}, method='OPTIONS')[0], 403)
    def test_native_cep_file_origin_requires_hmac_and_has_exact_cors(self):
        self.assertEqual(self.http('/v1/panel/hello',{},headers={'Origin':'file://'})[0],401)
        body=b'{}';endpoint='/v1/panel/hello'
        headers=request_headers(self.config['panel_token'],'127.0.0.1:'+str(self.port),endpoint,body,instance='hello')
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        conn.request('POST',endpoint,body,{'Content-Type':'application/json','Origin':'file://',**headers})
        response=conn.getresponse();raw=response.read()
        self.assertEqual(response.status,200)
        self.assertEqual(response.getheader('Access-Control-Allow-Origin'),'file://')
        self.assertEqual(response.getheader('Access-Control-Expose-Headers'),'X-Animate-Signature')
        check_response(self.config['panel_token'],headers['X-Animate-Nonce'],response.status,raw,response.getheader('X-Animate-Signature'))
        conn.close()
        self.assertEqual(self.http(endpoint,{},headers={'Origin':'file://','Access-Control-Request-Method':'POST'},method='OPTIONS')[0],204)
    def test_duplicate_nonfinite_oversize_and_unknown(self):
        token = self.config['panel_token']
        for body in [b'{"session":"a","session":"b"}', b'{"session":NaN}', b'[1,2]', b'{']:
            self.assertEqual(self.http('/v1/panel/register', body, token)[0], 400)
        self.assertEqual(self.http('/v1/panel/register', b'x' * (MAX_BODY + 1), token)[0], 413)
        self.assertEqual(self.http('/v1/panel/unknown', {}, token)[0], 404)
    def test_duplicate_host_and_auth_headers(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.putrequest('POST', '/v1/panel/register', skip_host=True)
        conn.putheader('Host', '127.0.0.1:' + str(self.port)); conn.putheader('Host', 'evil.test')
        conn.putheader('Authorization', 'Bearer ' + self.config['panel_token']); conn.putheader('Content-Length', '2'); conn.endheaders(b'{}')
        self.assertEqual(conn.getresponse().status, 403); conn.close()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.putrequest('POST', '/v1/panel/register')
        conn.putheader('Authorization', 'Bearer ' + self.config['panel_token']); conn.putheader('Authorization', 'Bearer ' + self.config['panel_token'])
        conn.putheader('Content-Length', '2'); conn.endheaders(b'{}')
        self.assertEqual(conn.getresponse().status, 401); conn.close()
    def test_legitimate_round_trip_and_session_binding(self):
        self.register()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.http, '/v1/command', {'action': 'getDocuments', 'options': {}}, self.config['client_token'])
            status, result = self.http('/v1/panel/next', {'session': self.session}, self.config['panel_token'])
            self.assertEqual(status, 200); packet = result['data']
            reply = {'session': 'd' * 32, 'id': packet['id'], 'result': {'ok': True, 'data': []}}
            self.assertEqual(self.http('/v1/panel/response', reply, self.config['panel_token'])[0], 400)
            reply['session'] = self.session
            self.assertEqual(self.http('/v1/panel/response', reply, self.config['panel_token'])[0], 200)
            self.assertEqual(future.result(timeout=3), (200, {'ok': True, 'data': []}))
            self.assertEqual(self.http('/v1/panel/response', reply, self.config['panel_token'])[0], 400)
    def test_disconnect_releases_pending_and_does_not_migrate(self):
        self.register()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.server.broker.command, 'getDocuments', {})
            packet = self.server.broker.next(self.session)
            self.server.broker.disconnect(self.session)
            with self.assertRaisesRegex(ValueError, 'disconnected'): future.result(timeout=3)
            self.server.broker.register('d' * 32)
            with self.assertRaises(ValueError): self.server.broker.response('d' * 32, packet['id'], {'ok': True, 'data': []})
    def test_raw_disabled_no_host_dispatch(self):
        self.register()
        result = self.http('/v1/command', {'action': 'executeExtendScript', 'options': {'document_id': 1, 'script': 'return 1;'}}, self.config['client_token'])
        self.assertEqual(result[0], 400)
        self.assertEqual(len(self.server.broker.pending), 0)
    def test_response_before_dispatch_rejected(self):
        broker = self.server.broker; broker.register(self.session)
        item = Pending('getDocuments', {}, self.session); broker.pending[item.packet['id']] = item
        with self.assertRaises(ValueError): broker.response(self.session, item.packet['id'], {'ok': True, 'data': []})
        with self.assertRaises(ValueError): broker.response(self.session, {}, {'ok': True, 'data': []})
        broker.pending.clear()
    def test_frame_export_through_broker_and_adapter(self):
        self.register(); self.config['port'] = self.port
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(adapter.call_tool, self.config, 'create_preview', {'document_id': 7, 'timeline_index': 0, 'start_frame': 0, 'end_frame': 2})
            packet = self.server.broker.next(self.session)
            from urllib.parse import urlparse, unquote
            job = Path(unquote(urlparse(packet['options']['output_uri']).path))
            self.assertEqual(job.parent, self.config['output_dir'])
            for i in range(3): (job / ('frame-%06d.png' % (i + 1))).write_bytes(png())
            self.server.broker.response(self.session, packet['id'], {'ok': True, 'data': {'frame_rate': 24, 'document_name': 'scene', 'count': 3}})
            result = future.result(timeout=3)
            self.assertFalse(result['isError']); metadata = json.loads(result['content'][0]['text'])
            frame = adapter.call_tool(self.config, 'get_frame', {'run_id': metadata['run_id'], 'index': 1})
            self.assertEqual(frame['content'][0]['type'], 'image')


    def test_malformed_host_payload_returns_controlled_error(self):
        self.register()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.http, '/v1/command', {'action': 'getTimeline', 'options': {'document_id': 1}}, self.config['client_token'])
            packet = self.server.broker.next(self.session)
            self.server.broker.response(self.session, packet['id'], {'ok': True, 'data': []})
            status, result = future.result(timeout=3)
            self.assertEqual(status, 400)
            self.assertEqual(result['error'], 'Invalid host response')


class ProtocolTests(LocalTest):
    def test_stdio_initialize_notifications_errors_and_tools(self):
        msgs = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion': '2025-06-18'}),
                dict(jsonrpc='2.0', method='notifications/initialized'),
                dict(jsonrpc='2.0', id=2, method='tools/list'),
                dict(jsonrpc='2.0', id=3, method='tools/call', params={'name': 'execute_extend_script', 'arguments': {'document_id': 1, 'script': 'return 1;'}}),
                dict(jsonrpc='2.0', id=4, method='absent')]
        env = dict(os.environ, ANIMATE_MCP_CONFIG=str(self.filename))
        result = subprocess.run([sys.executable, str(ROOT / 'mcp/an-mcp.py')], input='\n'.join(map(json.dumps, msgs)) + '\n', capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0); self.assertEqual(result.stderr, '')
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(len(responses[1]['result']['tools']), 24)
        self.assertNotIn('execute_extend_script',[t['name'] for t in responses[1]['result']['tools']])
        self.assertTrue(responses[2]['result']['isError'])
        self.assertEqual(responses[3]['error']['code'], -32601)
        self.assertNotIn(self.config['client_token'], result.stdout)
    def test_stdio_nonfinite_and_oversize_fail_closed(self):
        env = dict(os.environ, ANIMATE_MCP_CONFIG=str(self.filename))
        result = subprocess.run([sys.executable, str(ROOT / 'mcp/an-mcp.py')], input=b'{"jsonrpc":"2.0","id":NaN}\n', capture_output=True, env=env)
        self.assertEqual(json.loads(result.stdout)['error']['code'], -32700)
        result = subprocess.run([sys.executable, str(ROOT / 'mcp/an-mcp.py')], input=b'x' * (MAX_BODY + 1) + b'\n', capture_output=True, env=env)
        self.assertNotEqual(result.returncode, 0); self.assertEqual(result.stdout, b'')
    def test_protocol_invalid_ids_and_arguments(self):
        protocol = adapter.Protocol(self.config)
        self.assertEqual(protocol.handle({'jsonrpc': '2.0', 'id': True})['error']['code'], -32600)
        self.assertEqual(protocol.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['error']['code'], -32602)
        protocol.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'initialize'})
        for args in [{}, {'run_id': '../', 'index': 0}, {'run_id': 'run-' + '0' * 32, 'index': True}, {'run_id': 'run-' + '0' * 32, 'index': 0, 'path': '/etc'}]:
            result = protocol.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'get_frame', 'arguments': args}})
            self.assertTrue(result['result']['isError'])



class AuthenticationRegressionTests(HTTPFixture):
    def test_response_proof_and_replay_expiry_body_and_instance_binding(self):
        path = '/v1/panel/register'; body = json.dumps({'session': self.session}).encode()
        host = '127.0.0.1:' + str(self.port)
        headers = request_headers(self.config['panel_token'], host, path, body, instance=self.server.instance)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('POST', path, body, {'Content-Type': 'application/json', **headers})
        response = conn.getresponse(); raw = response.read()
        check_response(self.config['panel_token'], headers['X-Animate-Nonce'], response.status, raw, response.headers.get('X-Animate-Signature'))
        self.assertEqual(response.status, 200); conn.close()
        self.assertEqual(self.http(path, body, headers=headers)[0], 401)
        fresh = request_headers(self.config['panel_token'], host, path, body, instance=self.server.instance)
        self.assertEqual(self.http(path, body + b' ', headers=fresh)[0], 401)
        expired = request_headers(self.config['panel_token'], host, path, body, stamp=str(int(time.time()) - 60), instance=self.server.instance)
        self.assertEqual(self.http(path, body, headers=expired)[0], 401)
        old_instance = request_headers(self.config['panel_token'], host, path, body, instance=self.server.instance)
        self.server.instance = 'f' * 32
        self.assertEqual(self.http(path, body, headers=old_instance)[0], 401)
    def test_fast_reconnect_old_poll_cannot_consume_new_command(self):
        broker = self.server.broker; broker.register(self.session)
        old_queue = broker.commands; old_get = old_queue.get; waiting = threading.Event()
        def get(*args, **kwargs):
            waiting.set(); return old_get(*args, **kwargs)
        old_queue.get = get
        with concurrent.futures.ThreadPoolExecutor() as pool:
            old_poll = pool.submit(broker.next, self.session)
            self.assertTrue(waiting.wait(2))
            broker.disconnect(self.session); new_session = 'd' * 32; broker.register(new_session)
            command = pool.submit(broker.command, 'getDocuments', {})
            packet = broker.next(new_session)
            self.assertEqual(packet['session'], new_session)
            broker.response(new_session, packet['id'], {'ok': True, 'data': []})
            self.assertEqual(command.result(timeout=2), [])
            with self.assertRaises(ValueError): old_poll.result(timeout=2)
    def test_fake_local_listener_gets_no_secret_or_command_and_response_rejected(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        captured = []
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(inner):
                body = inner.rfile.read(int(inner.headers['Content-Length']))
                captured.append((dict(inner.headers), body))
                response = b'{"ok":true,"data":{"instance":"dddddddddddddddddddddddddddddddd"}}'
                inner.send_response(200); inner.send_header('Content-Length', str(len(response)))
                inner.send_header('X-Animate-Signature', '0' * 64); inner.end_headers(); inner.wfile.write(response)
        fake = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        thread = threading.Thread(target=fake.serve_forever, daemon=True); thread.start()
        cfg = dict(self.config, port=fake.server_port)
        try:
            with self.assertRaisesRegex(ValueError, 'authentication failed'): adapter.request(cfg, 'getDocuments', {})
            self.assertEqual(len(captured), 1)
            self.assertNotIn(self.config['client_token'], str(captured))
            self.assertEqual(captured[0][1], b'{}')
        finally:
            fake.shutdown(); fake.server_close(); thread.join(timeout=2)


class StrictParserRegressionTests(LocalTest):
    def test_duplicate_fields_nonfinite_exponent_and_configuration_rejected(self):
        for text in ['{"x":1,"x":2}', '{"x":1e309}', '{"x":Infinity}', '{"x":NaN}']:
            with self.subTest(text=text), self.assertRaises(ValueError): strict_json(text)
        protocol = adapter.Protocol(self.config)
        env = dict(os.environ, ANIMATE_MCP_CONFIG=str(self.filename))
        result = subprocess.run([sys.executable, str(ROOT / 'mcp/an-mcp.py')], input=b'{"jsonrpc":"2.0","id":1,"method":"ping","method":"initialize"}\n', capture_output=True, env=env)
        self.assertEqual(json.loads(result.stdout)['error']['code'], -32700)
        self.filename.write_text(json.dumps(self.data)[:-1] + ', "port": 3100}')
        with self.assertRaises(ValueError): load_config(str(self.filename))

if __name__ == '__main__': unittest.main()
