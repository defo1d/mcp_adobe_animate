import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp'))
from bridge import Server
from config import load_config


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        self.filename = self.root / 'config.json'
        self.filename.write_text(json.dumps({'client_token': 'a' * 64, 'panel_token': 'b' * 64,
            'output_dir': str(self.root / 'exports'), 'port': self.port,
            'allow_scripts': False, 'ffmpeg_path': None}))
        self.filename.chmod(0o600)
        self.env = dict(os.environ, ANIMATE_MCP_CONFIG=str(self.filename))
        self.request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                   'params': {'protocolVersion': '2025-06-18'}}) + '\n'

    def tearDown(self):
        self.temp.cleanup()

    def launch(self):
        return subprocess.run([sys.executable, str(ROOT / 'mcp/launch.py')], input=self.request,
                              text=True, capture_output=True, env=self.env, timeout=10)

    def test_owned_bridge_exits_with_stdio(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['result']['serverInfo']['name'], 'animate-mcp-safe')
        with socket.socket() as s:
            self.assertNotEqual(s.connect_ex(('127.0.0.1', self.port)), 0)

    def test_existing_authenticated_bridge_is_shared_and_not_stopped(self):
        with Server(load_config(str(self.filename))) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                result = self.launch()
                self.assertEqual(result.returncode, 0, result.stderr)
                with socket.socket() as s:
                    self.assertEqual(s.connect_ex(('127.0.0.1', self.port)), 0)
            finally:
                server.shutdown(); worker.join()

    def test_fake_server_cannot_be_reused_or_receive_the_key(self):
        captured = []
        class Fake(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(dict(self.headers))
                self.rfile.read(int(self.headers['Content-Length']))
                raw = b'{"ok":true,"data":{"instance":"00000000000000000000000000000000"}}'
                self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args):
                pass
        with http.server.HTTPServer(('127.0.0.1', self.port), Fake) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                result = self.launch()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('a' * 64, json.dumps(captured))
            finally:
                server.shutdown(); worker.join()
