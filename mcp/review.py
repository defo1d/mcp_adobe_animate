"""Long previews and render diagnostics, restricted to generated private artifacts."""
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import struct
import uuid
import zlib
from config import MAX_EXPORT_BYTES
from preview import create_job, find_job, read_png, finish_frames, project_file, encode_mp4
from audio import read_cues, audio_file
from validation import integer


def read_manifest(job):
    from audio import regular
    from auth import strict_json
    fd=regular(job/'manifest.json',131072)
    with os.fdopen(fd) as stream: meta=strict_json(stream.read(131073))
    names=meta.get('frames'); numbers=meta.get('frame_numbers')
    if not isinstance(names,list) or not 1<=len(names)<=1440 or names!=['frame-%06d.png'%(i+1) for i in range(len(names))]: raise ValueError('Invalid generated frame manifest')
    if not isinstance(numbers,list) or len(numbers)!=len(names) or any(type(x) is not int or not 0<=x<=9999 for x in numbers): raise ValueError('Invalid source frames')
    fps=meta.get('source_fps')
    if type(fps) not in (int,float) or not math.isfinite(fps) or not 1<=fps<=120: raise ValueError('Invalid source frame rate')
    return meta


def sampled_pixels(data, dimensions):
    width,height=dimensions; bits,color,compression,filtering,interlace=struct.unpack('>BBBBB',data[24:29])
    channels={2:3,6:4}.get(color)
    if bits!=8 or not channels or compression or filtering or interlace:
        return None
    expected=height*(width*channels+1); compressed=[]; cursor=8
    while cursor<len(data):
        size=struct.unpack_from('>I',data,cursor)[0]
        if data[cursor+4:cursor+8]==b'IDAT': compressed.append(data[cursor+8:cursor+8+size])
        cursor+=size+12
    decoder=zlib.decompressobj(); raw=decoder.decompress(b''.join(compressed),expected+1)
    if len(raw)!=expected or not decoder.eof or decoder.unconsumed_tail: raise ValueError('PNG decompression exceeds expected raster')
    row_size=width*channels; previous=bytearray(row_size); samples=bytearray(); nontransparent=False
    stride_x=max(1,width//80); stride_y=max(1,height//45)
    def paeth(a,b,c):
        p=a+b-c; aa=abs(p-a); bb=abs(p-b); cc=abs(p-c)
        return a if aa<=bb and aa<=cc else (b if bb<=cc else c)
    for y in range(height):
        start=y*(row_size+1); method=raw[start]; row=bytearray(raw[start+1:start+1+row_size])
        if method>4: raise ValueError('Invalid PNG filter')
        if method:
            for i in range(row_size):
                left=row[i-channels] if i>=channels else 0; above=previous[i]; corner=previous[i-channels] if i>=channels else 0
                predictor=left if method==1 else (above if method==2 else ((left+above)//2 if method==3 else paeth(left,above,corner)))
                row[i]=(row[i]+predictor)&255
        nontransparent=nontransparent or channels==3 or any(row[3::4])
        if y%stride_y==0:
            for x in range(0,width,stride_x):
                offset=x*channels; samples.extend(row[offset:offset+channels])
                if channels==3: samples.append(255)
        previous=row
    return dict(samples=bytes(samples),all_transparent=not nontransparent,transparent_sample_fraction=round(sum(alpha==0 for alpha in samples[3::4])/(len(samples)//4),6))


def review(config,run_id,indices):
    job=find_job(config,run_id); meta=read_manifest(job)
    if not isinstance(indices,list) or not 1<=len(indices)<=24 or any(type(i) is not int for i in indices) or indices!=sorted(set(indices)): raise ValueError('Choose 1 to 24 distinct increasing frame indices')
    results=[]; previous=None; warnings=[]
    for index in indices:
        integer(index,0,len(meta['frames'])-1)
        data,size=read_png(job/meta['frames'][index]); pixels=sampled_pixels(data,size)
        entry=dict(index=index,source_frame=meta['frame_numbers'][index],dimensions=size,png_sha256=hashlib.sha256(data).hexdigest())
        if pixels:
            sample=pixels['samples']; entry.update(sample_sha256=hashlib.sha256(sample).hexdigest(),all_transparent=pixels['all_transparent'],transparent_sample_fraction=pixels['transparent_sample_fraction'])
            if .02<=pixels['transparent_sample_fraction']<1: warnings.append(dict(frame=index,reason='Partial transparency: inspect stage/camera coverage or intended alpha'))
            if previous is not None and len(sample)==len(previous):
                entry['mean_sample_change']=round(sum(abs(a-b) for a,b in zip(sample,previous))/len(sample),4)
                entry['changed_sample_fraction']=round(sum(a!=b for a,b in zip(sample,previous))/len(sample),6)
                if sample==previous: warnings.append(dict(frame=entry['source_frame'],kind='identical_sample',meaning='May be an intentional hold; inspect in context'))
            previous=sample
            if pixels['all_transparent']: warnings.append(dict(frame=entry['source_frame'],kind='fully_transparent_render'))
        else:
            entry['metrics_unavailable']='Raster uses an unsupported PNG encoding; image remains available for visual review'
        results.append(entry)
    name='review-'+uuid.uuid4().hex+'.html'
    cards=''.join('<figure><img src="'+meta['frames'][e['index']]+'" alt="Frame '+str(e['source_frame']+1)+'"><figcaption>Frame '+str(e['source_frame']+1)+' · '+format(e['source_frame']/meta['source_fps'],'.2f')+' s</figcaption></figure>' for e in results)
    page='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' file:; style-src \'self\'; object-src \'none\'; base-uri \'none\'"><title>Animation contact sheet</title><link rel="stylesheet" href="review.css"></head><body><h1>Animation contact sheet</h1><p>Original Animate renders. Numerical warnings require artistic interpretation.</p><main>'+cards+'</main></body></html>'
    with (job/name).open('x') as stream: stream.write(page)
    # Static stylesheet, generated in a private artifact directory.
    stylesheet=job/'review.css'
    if not stylesheet.exists():
        with stylesheet.open('x') as stream: stream.write('body{font:15px system-ui;background:#171b20;color:#eee;margin:24px}main{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}figure{margin:0}img{width:100%;display:block}figcaption{padding:8px;background:#252c33}')
    return dict(run_id=run_id,contact_sheet=str(job/name),frames=results,warnings=warnings,
        limitations='Sample-grid metrics detect gross changes/blank alpha; they do not certify motion quality, identity, pose correctness or continuity')


def export_movie(config,args,request):
    if not config['ffmpeg_path']: raise ValueError('Configure an existing FFmpeg before exporting a movie')
    start=integer(args['start_frame'],0,9999); end=integer(args['end_frame'],start,min(9999,start+1439))
    include_audio=args.get('audio',True)
    if type(include_audio) is not bool: raise ValueError('audio must be boolean')
    scope={k:args[k] for k in ('document_id','project_run_id','timeline_index')}
    inspected=request(config,'inspectAnimation',{**scope,'layers':[],'start_frame':start,'end_frame':min(end,start+239),'symbol_name':None})
    state=inspected['state']; fps=state['frame_rate']
    if end>=state['frame_count']: raise ValueError('Movie range exceeds timeline')
    project=project_file(config,args['project_run_id']); cues=read_cues(project) if include_audio else []; inputs=[]
    for cue in cues:
        path,meta=audio_file(config,cue['audio_run_id'])
        inspection=request(config,'inspectAnimation',{**scope,'layers':[cue['layer']],'start_frame':cue['start_frame'],'end_frame':cue['start_frame'],'symbol_name':None})
        frames=inspection['state']['layers'][0]['keyframes']
        if len(frames)!=1 or frames[0]['frame']!=cue['start_frame'] or frames[0]['sound']!=cue['sound_name'] or frames[0]['sound_sync']!='stream' or frames[0].get('sound_loop')!=1:
            raise ValueError('Native audio cues changed; cannot claim an exact audio preview')
        delay=(cue['start_frame']-start)/fps
        if delay < (end-start+1)/fps and delay+meta['duration']>0: inputs.append((path,delay,meta['duration']))
    movie=create_job(config); total=0; ordinal=0; chunks=[]
    for begin in range(start,end+1,240):
        finish=min(end,begin+239)
        result=request(config,'exportManagedFrames',{**scope,'start_frame':begin,'end_frame':finish,'step':1})
        job=find_job(config,result['run_id']); chunk=read_manifest(job)
        if chunk['source_fps']!=fps or tuple(chunk['dimensions'])!=(state['width'],state['height']): raise ValueError('Scene/frame rate changed during export')
        chunks.append(result['run_id'])
        for name in chunk['frames']:
            data,_=read_png(job/name); total+=len(data)
            if total>MAX_EXPORT_BYTES: raise ValueError('Movie PNG sequence exceeds 256 MiB; export shorter shots')
            ordinal+=1
            with (movie/('frame-%06d.png'%ordinal)).open('xb') as stream: stream.write(data)
    result=finish_frames(config,movie,{'document_id':args['document_id'],'timeline_index':args['timeline_index'],'start_frame':start,'end_frame':end,'step':1},dict(frame_rate=fps,document_name='Managed animation movie'))
    result.update(encode_mp4(config,movie.name,audio_inputs=inputs))
    shutil.copyfile(movie/'preview.html',movie/'frames.html')
    video=Path(result['mp4']).name
    page='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; media-src \'self\' file:; style-src \'self\'; object-src \'none\'; base-uri \'none\'"><title>Animation movie</title><link rel="stylesheet" href="preview.css"></head><body><h1>Animation movie</h1><video controls preload="metadata" src="'+html.escape(video,quote=True)+'"></video><p><a href="frames.html">Frame-by-frame PNG player</a></p></body></html>'
    (movie/'preview.html').write_text(page)
    result.update(duration_seconds=ordinal/fps,render_batches=chunks,project_run_id=args['project_run_id'],audio_cue_count=len(inputs),
        consistency='Each batch pins the managed file, document and root timeline. Export is not atomic across batches; avoid concurrent manual edits while rendering.')
    return result
