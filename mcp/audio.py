"""Private, append-only PCM uploads and bounded cue records. No audio decoder."""
import base64
import hashlib
import json
import os
import stat
import struct
import fcntl
from preview import create_job, find_job
from auth import strict_json
from validation import integer, keys

MAX_AUDIO = 16*1024*1024


def regular(path, limit, write=False):
    fd = os.open(path, (os.O_RDWR if write else os.O_RDONLY) | getattr(os, 'O_NOFOLLOW', 0))
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > limit:
        os.close(fd); raise ValueError('Unsafe or oversized private audio file')
    return fd


def record(job):
    fd=regular(job/'audio.json', 4096)
    with os.fdopen(fd) as stream: value=strict_json(stream.read(4097))
    keys(value, ('kind','total_bytes','finalized'), ('sha256','rate','channels','sample_width','frame_count','duration'))
    if value['kind']!='animate-mcp-audio-v1' or type(value['finalized']) is not bool: raise ValueError('Invalid audio upload record')
    integer(value['total_bytes'],44,MAX_AUDIO)
    return value


def begin(config, total):
    integer(total,44,MAX_AUDIO); job=create_job(config)
    with (job/'audio.json').open('x') as stream: json.dump(dict(kind='animate-mcp-audio-v1',total_bytes=total,finalized=False),stream)
    fd=os.open(job/'audio.wav',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.close(fd)
    return dict(run_id=job.name,offset=0,total_bytes=total)


def append(config, run_id, offset, encoded):
    job=find_job(config,run_id); integer(offset,0,MAX_AUDIO)
    if not isinstance(encoded,str) or not 1<=len(encoded)<=65536: raise ValueError('Audio chunk exceeds bounds')
    chunk=base64.b64decode(encoded,validate=True)
    if not 1<=len(chunk)<=49152: raise ValueError('Audio chunk exceeds expected upload size')
    fd=regular(job/'audio.wav',MAX_AUDIO,True)
    with os.fdopen(fd,'r+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        meta=record(job)
        if meta['finalized']: raise ValueError('Finalized audio is immutable')
        if offset+len(chunk)>meta['total_bytes']: raise ValueError('Audio chunk exceeds expected upload size')
        if os.fstat(stream.fileno()).st_size!=offset: raise ValueError('Audio offset changed; never blindly retry an append')
        stream.seek(offset); stream.write(chunk)
    return dict(run_id=run_id,offset=offset+len(chunk),total_bytes=meta['total_bytes'])


def inspect_pcm(data):
    if not 44<=len(data)<=MAX_AUDIO or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE' or struct.unpack_from('<I',data,4)[0]!=len(data)-8:
        raise ValueError('Only complete RIFF PCM WAV files are accepted')
    cursor=12; fmt=None; pcm=None; count=0
    while cursor<len(data):
        count+=1
        if count>4096 or cursor+8>len(data): raise ValueError('Invalid WAV chunks')
        kind=data[cursor:cursor+4]; length=struct.unpack_from('<I',data,cursor+4)[0]; start=cursor+8; end=start+length
        if end+(length&1)>len(data): raise ValueError('Truncated WAV chunk')
        if kind==b'fmt ':
            if fmt is not None or length not in (16,18): raise ValueError('Unsupported PCM format')
            tag,channels,rate,byte_rate,align,bits=struct.unpack_from('<HHIIHH',data,start)
            if tag!=1 or channels not in (1,2) or not 8000<=rate<=48000 or bits not in (8,16,24,32): raise ValueError('Unsupported PCM parameters')
            if align!=channels*(bits//8) or byte_rate!=rate*align or (length==18 and data[start+16:start+18]!=b'\0\0'):
                raise ValueError('Inconsistent PCM parameters')
            fmt=(channels,rate,align,bits)
        elif kind==b'data':
            if pcm is not None or fmt is None: raise ValueError('Duplicate or misplaced PCM data')
            pcm=(start,length)
        elif length>65536: raise ValueError('Oversized ancillary WAV chunk')
        cursor=end+(length&1)
    if fmt is None or pcm is None or pcm[1]<fmt[2] or pcm[1]%fmt[2]: raise ValueError('Incomplete PCM frames')
    channels,rate,align,bits=fmt; frames=pcm[1]//align
    if frames/rate>60: raise ValueError('Audio exceeds 60 seconds')
    return dict(rate=rate,channels=channels,sample_width=bits//8,frame_count=frames,duration=frames/rate,sha256=hashlib.sha256(data).hexdigest())


def finalize(config, run_id):
    job=find_job(config,run_id)
    fd=regular(job/'audio.wav',MAX_AUDIO)
    with os.fdopen(fd,'rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        meta=record(job); data=stream.read(MAX_AUDIO+1)
        if len(data)!=meta['total_bytes']: raise ValueError('Audio upload is incomplete')
        result=inspect_pcm(data)
        if meta['finalized']:
            if meta['sha256']!=result['sha256']: raise ValueError('Finalized audio changed')
            return dict(run_id=run_id,**result)
        metadata_fd=regular(job/'audio.json',4096,True)
        with os.fdopen(metadata_fd,'r+') as metadata:
            metadata.seek(0); json.dump({**meta,**result,'finalized':True},metadata); metadata.truncate()
    return dict(run_id=run_id,**result)


def audio_file(config, run_id):
    job=find_job(config,run_id); meta=record(job)
    if not meta['finalized']: raise ValueError('Finalize the PCM upload first')
    actual=finalize(config,run_id)
    if actual['sha256']!=meta['sha256']: raise ValueError('PCM content changed')
    return job/'audio.wav',actual


def read_cues(project):
    path=project.parent/'audio-cues.json'
    if not path.exists(): return []
    fd=regular(path,16384)
    with os.fdopen(fd) as stream: cues=strict_json(stream.read(16385))
    if not isinstance(cues,list) or len(cues)>32: raise ValueError('Invalid audio cue record')
    for cue in cues:
        keys(cue,('audio_run_id','layer','start_frame','sound_name'))
        integer(cue['start_frame'],0,9999)
        if any(not isinstance(cue[k],str) or not 1<=len(cue[k])<=128 for k in ('audio_run_id','layer','sound_name')): raise ValueError('Invalid cue identity')
    return cues


def add_cue(project, cue):
    path=project.parent/'audio-cues.json'
    flags=os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,'r+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>16384: raise ValueError('Unsafe cue record')
        cues=read_cues(project) if info.st_size else []
        if len(cues)>=32 or any(c['layer']==cue['layer'] for c in cues): raise ValueError('Audio cue limit or duplicate layer')
        cues.append(cue); stream.seek(0); json.dump(cues,stream); stream.truncate()
