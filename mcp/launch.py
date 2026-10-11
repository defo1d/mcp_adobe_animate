#!/usr/bin/env python3
"""Start a loopback bridge for the lifetime of the stdio MCP client."""
from pathlib import Path
import errno
import importlib.util
import runpy
import threading
from bridge import Server
from config import load_config


def main():
    config = load_config()
    try:
        server = Server(config)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        # Multiple local Codex clients may share a bridge, but only after
        # mutual HMAC authentication. Never trust an occupied port alone.
        spec = importlib.util.spec_from_file_location('animate_adapter', Path(__file__).with_name('an-mcp.py'))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        adapter.exchange(config, '/v1/hello', {})
        adapter.main()
        return
    with server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            runpy.run_path(str(Path(__file__).with_name('an-mcp.py')), run_name='__main__')
        finally:
            server.shutdown()
            worker.join(timeout=5)


if __name__ == '__main__':
    main()
