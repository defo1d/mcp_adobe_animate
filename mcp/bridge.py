#!/usr/bin/env python3
"""Authenticated, bounded, loopback-only command broker. Python standard library only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import queue
import re
import threading
import sys
import time
import uuid
from config import MAX_BODY, load_config, prepare_root
from preview import create_job, finish_frames, read_png, project_file
from validation import keys, validate_command
from auth import strict_json, check_request, response_signature


class Pending:
    def __init__(self, action, options, session):
        self.packet = {'id': uuid.uuid4().hex, 'action': action, 'options': options,
                       'session': session, 'expires_at': int((time.time() + 120) * 1000)}
        self.event = threading.Event()
        self.result = None
        self.dispatched = False


class Broker:
    def __init__(self, config):
        self.config = config
        prepare_root(config)
        self.lock = threading.Lock()
        self.commands = queue.Queue(maxsize=8)
        self.pending = {}
        self.session = None
        self.last_poll = 0
        self.poll_session = None

    def disconnect(self, session):
        with self.lock:
            if session != self.session:
                raise ValueError('Panel session changed')
            self.session = None
            self.poll_session = None
            for item in self.pending.values():
                item.result = {'ok': False, 'error': 'Panel disconnected; operation may already have started'}
                item.event.set()
            self.pending.clear()
            while not self.commands.empty():
                self.commands.get_nowait()

    def register(self, session):
        if not isinstance(session, str) or not re.fullmatch('[0-9a-f]{32}', session):
            raise ValueError('Invalid panel session')
        with self.lock:
            if self.session == session:
                return {'connected': True, 'allow_scripts': self.config['allow_scripts']}
            if self.session and self.session != session and time.monotonic() - self.last_poll < 35:
                raise ValueError('Another panel is already connected')
            # Do not migrate operations to a new panel.
            for item in self.pending.values():
                item.result = {'ok': False, 'error': 'Panel session replaced'}
                item.event.set()
            self.pending.clear()
            while not self.commands.empty():
                self.commands.get_nowait()
            # An old poll keeps its old queue; it must never consume a new session's work.
            self.commands = queue.Queue(maxsize=8)
            self.poll_session = None
            self.session = session
            self.last_poll = time.monotonic()
        return {'connected': True, 'allow_scripts': self.config['allow_scripts']}

    def next(self, session):
        with self.lock:
            if session != self.session or self.poll_session is not None:
                raise ValueError('Invalid session or concurrent poll')
            self.poll_session = session
            commands = self.commands
            self.last_poll = time.monotonic()
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    item = commands.get(timeout=1)
                except queue.Empty:
                    with self.lock:
                        if session != self.session:
                            raise ValueError('Panel disconnected')
                    continue
                with self.lock:
                    if (session == self.session and item.packet['id'] in self.pending
                            and item.packet['expires_at'] > time.time() * 1000):
                        item.dispatched = True
                        return item.packet
            return None
        finally:
            with self.lock:
                if self.poll_session == session:
                    self.poll_session = None
                if self.session == session:
                    self.last_poll = time.monotonic()

    def response(self, session, request_id, result):
        if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
            raise ValueError('Invalid command ID')
        with self.lock:
            item = self.pending.get(request_id)
            if session != self.session or not item or not item.dispatched or item.packet['session'] != session:
                raise ValueError('Unknown, expired or foreign command')
            if item.event.is_set():
                raise ValueError('Duplicate response')
            keys(result, ('ok',), ('data', 'error'))
            if type(result['ok']) is not bool:
                raise ValueError('Invalid response status')
            if result['ok'] and 'data' not in result:
                raise ValueError('Response has no data')
            item.result = result
            item.event.set()
        return {'accepted': True}

    def command(self, action, options):
        validate_command(action, options, self.config['allow_scripts'])
        with self.lock:
            if not self.session or time.monotonic() - self.last_poll > 35:
                raise ValueError('Open the Animate panel and pair it first')
            if len(self.pending) >= 8:
                raise ValueError('Too many pending commands')
            session = self.session
        options = dict(options)
        job = None
        if action in {'createProject', 'exportFrames', 'exportSpriteSheet', 'exportAllSpriteSheets', 'applyAnimation'}:
            job = create_job(self.config)
            options['output_uri'] = job.as_uri() + '/'
        elif action == 'openProject':
            options['project_uri'] = project_file(self.config,options['run_id']).as_uri()
        item = Pending(action, options, session)
        with self.lock:
            if session != self.session:
                raise ValueError('Panel disconnected')
            if len(self.pending) >= 8:
                raise ValueError('Too many pending commands')
            self.pending[item.packet['id']] = item
            try:
                self.commands.put_nowait(item)
            except queue.Full:
                self.pending.pop(item.packet['id'], None)
                raise ValueError('Command queue is full')
        try:
            if not item.event.wait(120):
                raise ValueError('Command timed out; it may already have started. Inspect the project before retrying.')
            result = item.result
            if not result['ok']:
                raise ValueError(str(result.get('error', 'Animate failed'))[:1024])
            data = result['data']
            expected_type = list if action == 'getDocuments' else dict
            if not isinstance(data, expected_type):
                raise ValueError('Invalid host response')
            if action == 'exportFrames':
                data = finish_frames(self.config, job, options, data)
            elif action == 'createProject':
                target = job / 'project.fla'
                info = target.lstat()
                if target.is_symlink() or not target.is_file() or not 1 <= info.st_size <= 134217728:
                    raise ValueError('Project was not saved safely; inspect the new document')
                with (job / 'project.json').open('x') as stream:
                    json.dump({'kind':'animate-mcp-project-v1','file':'project.fla'},stream)
                data.update(run_id=job.name,project_fla=str(project_file(self.config,job.name)))
            elif action in {'exportSpriteSheet', 'exportAllSpriteSheets'}:
                count = data.get('count') if isinstance(data, dict) else None
                if type(count) is not int or not 1 <= count <= 64:
                    raise ValueError('Invalid sprite export count')
                total = 0
                for i in range(count):
                    png, _ = read_png(job / ('sprite-%06d.png' % (i + 1)))
                    total += len(png)
                    if total > 256 * 1024 * 1024:
                        raise ValueError('Sprite export exceeds 256 MiB')
                data = {'run_id': job.name, 'count': count, 'directory': str(job)}
            elif action == 'applyAnimation':
                backup = job / 'backup.fla'
                if backup.is_symlink() or not backup.is_file() or backup.stat().st_size == 0:
                    raise ValueError('Backup was not created; inspect the document before retrying')
                data['backup'] = str(backup)
            return data
        finally:
            with self.lock:
                self.pending.pop(item.packet['id'], None)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Allows a clean restart during TCP TIME_WAIT; does not permit a second listener.
    allow_reuse_address = True
    def __init__(self, config, port=None):
        self.broker = Broker(config)
        self.config = config
        self.slots = threading.BoundedSemaphore(16)
        self.auth_lock = threading.Lock()
        self.auth_nonces = {}
        self.instance = uuid.uuid4().hex
        super().__init__(('127.0.0.1', config['port'] if port is None else port), Handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(3)
        return request, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass  # Do not log tokens, commands, project contents or file paths.

    def headers_ok(self):
        if self.client_address[0] != '127.0.0.1':
            return False
        host = '127.0.0.1:' + str(self.server.server_port)
        return (self.headers.get_all('Host') == [host]
                and self.headers.get('Origin') in (None, 'null', 'file://')
                and len(self.headers.get_all('Origin', [])) <= 1)

    def reply(self, status, value):
        if os.environ.get('ANIMATE_MCP_DIAGNOSTICS') == '1':
            # Opt-in integration diagnostics: never headers, keys, body, command, or project data.
            origin = self.headers.get('Origin')
            sys.stderr.write(json.dumps({'http_status':status,
                'origin_kind': origin if origin in (None,'null','file://') else 'other',
                'host_valid':self.headers.get_all('Host') == ['127.0.0.1:' + str(self.server.server_port)],
                'auth_header_present':bool(self.headers.get('Authorization')),
                'nonce_header_present':bool(self.headers.get('X-Animate-Nonce')),
                'request_authenticated':bool(getattr(self,'auth_nonce',None))})+'\n')
            sys.stderr.flush()
        data = json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
        if len(data) > MAX_BODY:
            status = 413
            data = b'{"ok":false,"error":"Bridge response exceeded size limit"}'
        self.send_response(status)
        if getattr(self, 'auth_nonce', None):
            self.send_header('X-Animate-Signature', response_signature(self.auth_key, self.auth_nonce, status, data))
        if self.headers.get('Origin') in ('null','file://'):
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Access-Control-Expose-Headers', 'X-Animate-Signature')
            self.send_header('Vary', 'Origin')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        if not self.headers_ok() or not self.path.startswith('/v1/panel/') or self.headers.get('Origin') not in ('null','file://'):
            return self.reply(403, {'error': 'Rejected origin'})
        if self.headers.get('Access-Control-Request-Method') != 'POST':
            return self.reply(403, {'error': 'Rejected method'})
        requested = {s.strip().lower() for s in self.headers.get('Access-Control-Request-Headers', '').split(',') if s.strip()}
        if requested - {'authorization', 'content-type', 'x-animate-nonce', 'x-animate-timestamp', 'x-animate-instance'}:
            return self.reply(403, {'error': 'Rejected headers'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods', 'POST')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Animate-Nonce, X-Animate-Timestamp, X-Animate-Instance')
        self.send_header('Vary', 'Origin')
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_POST(self):
        if not self.headers_ok():
            return self.reply(403, {'error': 'Rejected host or origin'})
        role = 'panel' if self.path.startswith('/v1/panel/') else 'client'
        key = self.server.config[role + '_token']
        auth = self.headers.get_all('Authorization', [])
        nonces = self.headers.get_all('X-Animate-Nonce', [])
        stamps = self.headers.get_all('X-Animate-Timestamp', [])
        instances = self.headers.get_all('X-Animate-Instance', [])
        hello = self.path in ('/v1/hello', '/v1/panel/hello')
        expected_instance = 'hello' if hello else self.server.instance
        if (len(auth) != 1 or len(nonces) != 1 or len(stamps) != 1 or instances != [expected_instance]
                or not re.fullmatch('HMAC [0-9a-f]{64}', auth[0])):
            return self.reply(401, {'error': 'Authentication required'})
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not lengths[0].isdigit():
            return self.reply(400, {'error': 'Invalid body framing'})
        length = int(lengths[0])
        if length > MAX_BODY:
            return self.reply(413, {'error': 'Body too large'})
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            return self.reply(415, {'error': 'JSON required'})
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete body')
            if not check_request(key, 'POST', self.headers['Host'], self.path, raw, auth[0], stamps[0], nonces[0], instances[0]):
                return self.reply(401, {'error': 'Authentication failed'})
            with self.server.auth_lock:
                now = time.monotonic()
                self.server.auth_nonces = {n: deadline for n, deadline in self.server.auth_nonces.items() if deadline > now}
                nonce_key = (role, nonces[0])
                if nonce_key in self.server.auth_nonces or len(self.server.auth_nonces) >= 4096:
                    return self.reply(401, {'error': 'Replay or authentication rate limit'})
                self.server.auth_nonces[nonce_key] = now + 61
            self.auth_nonce = nonces[0]
            self.auth_key = key
            body = strict_json(raw)
            broker = self.server.broker
            if hello:
                keys(body, ()); result = {'instance': self.server.instance}
            elif self.path == '/v1/panel/register':
                keys(body, ('session',)); result = broker.register(body['session'])
            elif self.path == '/v1/panel/next':
                keys(body, ('session',)); result = broker.next(body['session'])
            elif self.path == '/v1/panel/response':
                keys(body, ('session', 'id', 'result')); result = broker.response(body['session'], body['id'], body['result'])
            elif self.path == '/v1/panel/disconnect':
                keys(body, ('session',)); broker.disconnect(body['session']); result = {'disconnected': True}
            elif self.path == '/v1/command':
                keys(body, ('action', 'options')); result = broker.command(body['action'], body['options'])
            else:
                return self.reply(404, {'error': 'Unknown endpoint'})
            self.reply(200, {'ok': True, 'data': result})
        except (ValueError, TypeError, KeyError, RecursionError, OSError, queue.Empty) as error:
            self.reply(400, {'ok': False, 'error': str(error)[:1024]})


def main():
    config = load_config()
    with Server(config) as server:
        print('Animate bridge listening only on 127.0.0.1:' + str(server.server_port), flush=True)
        server.serve_forever()

if __name__ == '__main__':
    main()
