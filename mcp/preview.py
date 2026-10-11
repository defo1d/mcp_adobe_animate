"""Bounded local artifacts; never accept filenames, executable paths or URLs from tools."""
import base64
import html
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import uuid
import zlib
from config import MAX_FRAME_BYTES, MAX_EXPORT_BYTES, prepare_root

RUN_ID = re.compile(r"run-[0-9a-f]{32}\Z")


def create_job(config):
    root = prepare_root(config)
    name = 'run-' + uuid.uuid4().hex
    job = root / name
    job.mkdir(mode=0o700)
    return job


def find_job(config, name):
    if not isinstance(name, str) or not RUN_ID.fullmatch(name):
        raise ValueError("Invalid export identifier")
    job = prepare_root(config) / name
    info = job.lstat()
    if not stat.S_ISDIR(info.st_mode) or job.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Unsafe export directory")
    return job


def read_png(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 33 <= info.st_size <= MAX_FRAME_BYTES:
            raise ValueError("PNG size outside allowed bounds")
        data = stream.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n') or data[12:16] != b'IHDR':
        raise ValueError("Export did not produce a PNG")
    width, height = struct.unpack('>II', data[16:24])
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError("PNG dimensions outside allowed bounds")
    offset, chunks, image_data, ended = 8, 0, False, False
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        end = offset + 12 + length
        kind = data[offset + 4:offset + 8]
        if end > len(data) or chunks >= 50000:
            raise ValueError('Invalid PNG chunk bounds')
        crc = struct.unpack('>I', data[end - 4:end])[0]
        if zlib.crc32(data[offset + 4:end - 4]) & 0xffffffff != crc:
            raise ValueError('Invalid PNG checksum')
        if chunks == 0 and (kind != b'IHDR' or length != 13):
            raise ValueError('Invalid PNG header')
        if chunks > 0 and kind == b'IHDR':
            raise ValueError('Duplicate PNG header')
        image_data = image_data or kind == b'IDAT'
        offset = end
        chunks += 1
        if kind == b'IEND':
            if length != 0 or offset != len(data):
                raise ValueError('Invalid PNG ending')
            ended = True
            break
    if not image_data or not ended:
        raise ValueError('Incomplete PNG')
    return data, (width, height)


def project_file(config, run_id):
    job = find_job(config,run_id)
    fd = os.open(job / 'project.json',os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 4096:
            raise ValueError('Invalid project record')
        record = json.loads(stream.read(4097))
    if record != {'kind':'animate-mcp-project-v1','file':'project.fla'}:
        raise ValueError('Not an MCP-created project')
    target = job / 'project.fla'
    info = target.lstat()
    if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or not 1 <= info.st_size <= 134217728:
        raise ValueError('Unsafe or oversized project file')
    return target


def finish_frames(config, job, options, result):
    numbers = list(range(options['start_frame'], options['end_frame'] + 1, options['step']))
    names = ['frame-%06d.png' % (i + 1) for i in range(len(numbers))]
    total = 0
    dimensions = None
    for name in names:
        data, size = read_png(job / name)
        total += len(data)
        if total > MAX_EXPORT_BYTES or (dimensions is not None and dimensions != size):
            raise ValueError("Export exceeds bounds or changes dimensions")
        dimensions = size
    fps = result.get('frame_rate')
    if type(fps) not in (int, float) or not 1 <= fps <= 120:
        raise ValueError("Invalid frame rate from Animate")
    manifest = {'frames': names, 'frame_numbers': numbers, 'fps': fps / options['step'],
                'source_fps': fps, 'document_id': options['document_id'],
                'timeline_index': options['timeline_index'], 'dimensions': dimensions}
    (job / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    # No inline executable script and no untrusted document text in executable contexts.
    title = html.escape(str(result.get('document_name', 'Animate preview'))[:256])
    embedded = json.dumps(manifest).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    page = '''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; script-src 'self'; style-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'">
<title>Animate preview</title><link rel="stylesheet" href="preview.css"></head><body>
<h1>''' + title + '''</h1><img id="frame" alt="Exported animation frame">
<div><button id="play">Play</button><button id="previous">Previous</button><button id="next">Next</button>
<label>Speed <select id="speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label></div>
<input id="seek" type="range" min="0" value="0"><p id="position"></p>
<p>Timeline PNG preview; audio, ActionScript and runtime MovieClip playback are not simulated.</p>
<script type="application/json" id="manifest">''' + embedded + '''</script><script src="preview.js"></script></body></html>'''
    (job / 'preview.html').write_text(page, encoding='utf-8')
    assets = Path(__file__).parent / 'preview_assets'
    for name in ('preview.js', 'preview.css'):
        shutil.copyfile(assets / name, job / name)
    return {'run_id': job.name, 'frame_count': len(names), 'preview_html': str(job / 'preview.html'),
            'manifest': str(job / 'manifest.json'), 'frames_directory': str(job), 'source_fps': fps,
            'playback_fps': manifest['fps'], 'dimensions': dimensions, 'audio': False}


def frame_content(config, run_id, index):
    job = find_job(config, run_id)
    if type(index) is not int or not 0 <= index < 240:
        raise ValueError("Invalid frame index")
    data, _ = read_png(job / ('frame-%06d.png' % (index + 1)))
    return {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode('ascii')}


def encode_mp4(config, run_id):
    exe = config['ffmpeg_path']
    if not exe:
        raise ValueError("MP4 needs an explicitly configured existing ffmpeg; HTML playback needs none")
    job = find_job(config, run_id)
    # Read only the manifest created by us, without following symlinks.
    fd = os.open(job / 'manifest.json', os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd) as stream:
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise ValueError("Manifest too large")
    manifest = json.loads(raw)
    count = len(manifest['frames'])
    fps = manifest['fps']
    if not 1 <= count <= 240 or type(fps) not in (int, float) or not 0 < fps <= 120:
        raise ValueError("Invalid preview manifest")
    # Revalidate every input before the external encoder. Inputs are generated names only.
    for i in range(count):
        read_png(job / ('frame-%06d.png' % (i + 1)))
    destination = job / ('preview-' + uuid.uuid4().hex + '.mp4')
    args = [exe, '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
            '-protocol_whitelist', 'file', '-framerate', str(fps), '-start_number', '1',
            '-i', str(job / 'frame-%06d.png'), '-frames:v', str(count), '-an',
            '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-threads', '2', '-fs', str(MAX_EXPORT_BYTES), '-movflags', '+faststart', str(destination)]
    # No shell, PATH lookup, network input, inherited application tokens or prompts.
    subprocess.run(args, check=True, timeout=90, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={'PATH': '/usr/bin:/bin', 'HOME': str(job), 'TMPDIR': str(job)})
    if destination.is_symlink() or not destination.is_file() or not 1 <= destination.stat().st_size <= MAX_EXPORT_BYTES:
        raise ValueError("Invalid MP4 output")
    return {'mp4': str(destination), 'audio': False, 'run_id': run_id}
