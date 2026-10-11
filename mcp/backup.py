"""Validate a completed native FLA snapshot before copying a durable backup."""
import hashlib
import io
import os
import struct
import time
import zipfile
from audio import regular

MAX_FLA = 128 * 1024 * 1024


def validate_fla(data):
    if not 22 <= len(data) <= MAX_FLA or data[:4] != b'PK\x03\x04':
        raise ValueError('Incomplete native FLA snapshot')
    end = data.rfind(b'PK\x05\x06', max(0, len(data)-65557))
    if end < 0 or end+22 > len(data):
        raise ValueError('FLA snapshot has no completed directory')
    _, disk, directory_disk, disk_count, count, size, offset, comment = struct.unpack_from('<4s4H2IH', data, end)
    if disk or directory_disk or disk_count != count or not 1 <= count <= 2048 or end+22+comment != len(data) or not 0 <= offset < end:
        raise ValueError('Unsupported native FLA directory')
    # Animate 2024 writes an overstated central-directory size on this Mac.
    # Correct only the in-memory validation view; retain original Adobe bytes.
    view = bytearray(data)
    struct.pack_into('<I', view, end+12, end-offset)
    with zipfile.ZipFile(io.BytesIO(view)) as archive:
        entries = archive.infolist()
        if len(entries) != count or sum(entry.file_size for entry in entries) > MAX_FLA:
            raise ValueError('FLA archive exceeds validation budget')
        if 'DOMDocument.xml' not in archive.namelist() or any(entry.flag_bits & 1 or entry.compress_type not in (0, 8) for entry in entries):
            raise ValueError('Unsupported native FLA contents')
        if archive.testzip() is not None:
            raise ValueError('FLA snapshot CRC failed')
    return hashlib.sha256(data).hexdigest()


def preserve_snapshot(job, deadline=None):
    deadline = min(deadline, time.monotonic()+10) if deadline is not None else time.monotonic()+10
    while True:
        try:
            fd = regular(job/'snapshot.fla', MAX_FLA)
            with os.fdopen(fd, 'rb') as stream:
                data = stream.read(MAX_FLA+1)
            digest = validate_fla(data)
            break
        except (ValueError, FileNotFoundError, zipfile.BadZipFile, EOFError) as error:
            if time.monotonic() >= deadline:
                raise ValueError('Native snapshot did not complete; no edits applied') from error
            time.sleep(.1)
    fd = os.open(job/'backup.fla', os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return digest
