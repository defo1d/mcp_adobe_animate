"""Build an original 24-second classroom comedy in a NEW managed FLA.

Uses only the public, bounded MCP tools. Existing projects are never edited.
Run with ANIMATE_MCP_CONFIG set and the signed Animate panel connected.
Reports are private local artifacts. No voice downloads or raw JSFL.
"""
import argparse
import base64
import copy
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import wave
from mcp_client import MCP
from vector_art import artwork,mouth_frames
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp'))
from motion import evaluate, validate_tracks

def key(frame,values,**options):return dict(frame=frame,values=values,**options)
def track(layer,x,y,entries,**options):
    keys=[key(0,dict(x=x,y=y),interpolation='hold')]+entries
    keys=sorted({k['frame']:k for k in keys}.values(),key=lambda k:k['frame'])
    if keys[0]['frame']==0:keys[0]['values']={'x':x,'y':y,**keys[0]['values']}
    if keys[-1]['frame']<575:keys.append(key(575,{},interpolation='hold'))
    # Empty endpoint keys carry the preceding full value.
    for k in keys:
        if not k['values']:k['values']={'x':evaluate({'keys':keys[:keys.index(k)],'layer':layer,'instance':layer},k['frame'])['x']}
    return dict(layer=layer,instance=layer,keys=keys,**options)

class Demo:
    def __init__(self,report):
        self.client=MCP();self.report=report;self.scope=None;self.events=[];self.checkpoint=report/'result.json'
    def call(self,name,args=None):
        result=self.client.call(name,args);self.events.append(dict(tool=name,result=result))
        self.checkpoint.write_text(json.dumps(dict(scope=self.scope,events=self.events),ensure_ascii=False,indent=2))
        return result
    def inspect(self,layers=None,start=0,end=0,symbol=None):
        return self.call('get_animation_state',{**self.scope,'layers':layers or [],'start_frame':start,'end_frame':end,**({'symbol_name':symbol} if symbol else {})})
    def edit(self,name,args,**inspection):
        revision=self.inspect(**inspection)
        return self.call(name,{**self.scope,'revision_id':revision['revision_id'],**args})
    def author(self,symbols,instances,frames=576,target=None):
        print('Author:',target or 'root',[s['name'] for s in symbols],flush=True)
        return self.edit('author_scene',dict(frame_count=frames,symbols=symbols,instances=instances),symbol=target)
    def animate(self,tracks,symbol=None,step=2):
        validate_tracks(tracks,step)
        # Sample the complete original curves before splitting batches, so clipping
        # a shot never changes Bezier timing or a spatial arc's control points.
        for start in range(0,576,96):
            end=min(575,start+95);batch=[]
            for original in tracks:
                frames=sorted(set(range(start,end+1,step))|{start,end}|{k['frame'] for k in original['keys'] if start<=k['frame']<=end})
                if len(frames)>64:raise ValueError('Example exceeds per-track key budget')
                keys=[key(f,evaluate(original,f),interpolation='hold') for f in frames]
                if original.get('sync_to_timeline'):
                    for k in keys:k['values']['firstFrame']=k['frame']
                batch.append({**original,'keys':keys})
            self.call('plan_motion',dict(tracks=batch,step=step))
            result=self.edit('apply_motion',dict(tracks=batch,step=step),layers=[t['layer'] for t in batch],start=start,end=end,symbol=symbol)
            if not result.get('readback_verified'):raise RuntimeError('Native readback was not verified')
            print('Motion:',symbol or 'root',','.join(t['layer'] for t in batch),start,end,'verified',flush=True)
    def upload_chime(self):
        output=io.BytesIO();rate=22050
        samples=[]
        for i in range(int(rate*.28)):
            t=i/rate;envelope=math.exp(-t*18)*min(1,t/.006)
            samples.append(int(15000*envelope*(math.sin(2*math.pi*880*t)+.3*math.sin(2*math.pi*1320*t))))
        with wave.open(output,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(struct.pack('<'+'h'*len(samples),*samples))
        data=output.getvalue();run=self.call('begin_audio_upload',dict(total_bytes=len(data)))['run_id']
        for offset in range(0,len(data),49152):self.call('append_audio_chunk',dict(run_id=run,offset=offset,data_base64=base64.b64encode(data[offset:offset+49152]).decode()))
        self.call('finish_audio_upload',dict(run_id=run))
        self.edit('set_audio',dict(audio_run_id=run,layer='Phone_chime',start_frame=504))
    def build(self):
        deadline=time.monotonic()+90
        while True:
            try:baseline=self.call('get_documents');break
            except RuntimeError as e:
                if 'Open the Animate panel and pair it first' not in str(e) or time.monotonic()>=deadline:raise
                time.sleep(1)
        created=self.call('create_project',dict(width=1280,height=720,frame_rate=24,background='#d7d0ba',template='blank'))
        self.scope=dict(document_id=created['document_id'],project_run_id=created['run_id'],timeline_index=created['timeline_index'])
        self.call('get_animation_state',self.scope)
        sym=lambda name,frames:dict(name=name,frames=frames)
        place=lambda layer,symbol,x,y,**extra:dict(layer=layer,name=layer,symbol=symbol,x=x,y=y,**extra)
        self.author([sym('Classroom',[artwork('classroom')])],[place('Camera','Classroom',640,360)])
        # Each rig contains editable native head artwork and two graphic pose tracks.
        self.author([sym('LeftRig',[artwork('left_neutral',skin_only=True)]),sym('RightRig',[artwork('right_neutral',skin_only=True)]),sym('LeftBody',[artwork('left_body')]),sym('RightBody',[artwork('right_body')])],
            [place('LeftBody','LeftBody',-230,120),place('RightBody','RightBody',190,120),place('LeftHead','LeftRig',-230,-35,playback='play once'),place('RightHead','RightRig',190,-35,playback='play once')],target='Classroom')
        self.author([sym('Desk',[artwork('desk')]),sym('Hand',[artwork('hand')]),sym('Phone',[artwork('phone')])],
            [place('Desk','Desk',0,235),place('Hand','Hand',239,84),place('Phone','Phone',287,89)],target='Classroom')
        self.author([sym('Boast',[artwork('boast')]),sym('Notice',[artwork('announcement')]),sym('Reply',[artwork('reply')]),sym('Thud',[artwork('thud')])],
            [place('Boast','Boast',173,-215,alpha=0),place('Notice','Notice',73,-255,alpha=0),place('Reply','Reply',220,-230,alpha=0),place('Thud','Thud',310,164,alpha=0)],target='Classroom')
        for who,title in [('left','LeftRig'),('right','RightRig')]:
            self.author([sym(who+'Eyes',[artwork(who+'_'+e,eye_only=True) for e in ('neutral','blink','sideeye','panic')]),sym(who+'Mouth',mouth_frames())],
                [place('Eyes',who+'Eyes',0,0),place('Mouth',who+'Mouth',0,0)],target=title)
        left=track('LeftHead',-230,-35,[key(42,dict(rotation=-2)),key(62,dict(rotation=2),easing='ease_out'),key(86,dict(rotation=0),interpolation='hold'),key(210,dict(y=-29,rotation=3),easing='ease_in'),key(218,dict(y=-56,rotation=-7,scaleX=.94,scaleY=1.08),easing='back_out'),key(248,dict(y=-35,rotation=0,scaleX=1,scaleY=1),interpolation='hold'),key(442,dict(rotation=7),easing='ease_in_out'),key(465,dict(rotation=-3),interpolation='hold'),key(548,dict(rotation=0))],playback='play once',sync_to_timeline=True)
        right=track('RightHead',190,-35,[key(78,dict(rotation=-3),easing='ease_out'),key(105,dict(rotation=4),easing='ease_in_out'),key(132,dict(rotation=0),interpolation='hold'),key(208,dict(y=-27,rotation=4),easing='ease_in'),key(220,dict(y=-60,rotation=-8,scaleX=.93,scaleY=1.1),easing='back_out'),key(252,dict(y=-35,rotation=1,scaleX=1,scaleY=1),interpolation='hold'),key(365,dict(rotation=-6),easing='ease_out'),key(396,dict(rotation=4),interpolation='hold'),key(468,dict(rotation=0))],playback='play once',sync_to_timeline=True)
        self.animate([left,right],'Classroom')
        for title,talk,react in [('LeftRig',(48,84),216),('RightRig',(96,142),220)]:
            blinks=[]
            for f in (25,154,290,490,548):blinks.extend([key(f,dict(firstFrame=1),interpolation='hold'),key(f+3,dict(firstFrame=0),interpolation='hold')])
            blinks.extend([key(react,dict(firstFrame=3),interpolation='hold'),key(react+70,dict(firstFrame=2),interpolation='hold'),key(440,dict(firstFrame=2),interpolation='hold')])
            eyes=track('Eyes',0,0,blinks)
            mouths=[]
            for start,end in ([talk,(405,468)] if title=='RightRig' else [talk]):
                for i,f in enumerate(range(start,end,5)):mouths.append(key(f,dict(firstFrame=[1,4,2,1,0,3][i%6]),interpolation='hold'))
                mouths.append(key(end,dict(firstFrame=0),interpolation='hold'))
            mouths.extend([key(react,dict(firstFrame=5),interpolation='hold'),key(react+50,dict(firstFrame=4),interpolation='hold'),key(react+70,dict(firstFrame=0),interpolation='hold')])
            self.animate([eyes,track('Mouth',0,0,mouths)],title,step=12)
        body=[]
        for layer,x in [('LeftBody',-230),('RightBody',190)]:
            keys=[]
            for f in range(0,576,48):keys.append(key(f,dict(x=x,y=120+(2 if f%96 else 0),scaleY=1 if f%96 else 1.012),easing='ease_in_out'))
            body.append(track(layer,x,120,keys))
        self.animate(body,'Classroom',step=4)
        hand=track('Hand',239,84,[key(86,dict(rotation=-5),easing='ease_out'),key(116,dict(x=257,y=55,rotation=-15),easing='ease_in_out'),key(146,dict(x=239,y=84,rotation=0),interpolation='hold'),key(208,dict(y=92,rotation=8),easing='ease_in'),key(228,dict(y=60,rotation=-18),easing='back_out'),key(272,dict(y=84,rotation=0),interpolation='hold'),key(320,dict(x=252,y=97,rotation=15),easing='ease_out'),key(354,dict(x=235,y=120,rotation=0),interpolation='hold'),key(418,dict(x=247,y=96,rotation=-9),easing='ease_in_out'),key(460,dict(x=235,y=120,rotation=0))])
        phone=track('Phone',287,89,[key(310,dict(x=287,y=89,rotation=0),easing='ease_in',path=[dict(x=330,y=40),dict(x=400,y=130)]),key(336,dict(x=344,y=163,rotation=98),easing='bounce_out'),key(356,dict(x=344,y=162,rotation=90),interpolation='hold'),key(502,dict(rotation=90),easing='linear'),key(504,dict(rotation=84,y=160),easing='linear'),key(507,dict(rotation=96,y=162),easing='linear'),key(510,dict(rotation=90,y=162),interpolation='hold')])
        self.animate([hand,phone],'Classroom',step=2)
        def visible(layer,x,y,segments):
            entries=[key(0,dict(x=x,y=y,alpha=0),interpolation='hold')]
            for start,end in segments:entries.extend([key(start,dict(alpha=100),interpolation='hold'),key(end,dict(alpha=0),interpolation='hold')])
            return track(layer,x,y,entries)
        self.animate([visible('Boast',173,-215,[(96,164)]),visible('Notice',73,-255,[(192,575)]),visible('Reply',220,-230,[(405,491)]),visible('Thud',344,170,[(336,351),(504,516)])],'Classroom',step=12)
        camera=track('Camera',640,360,[key(0,dict(x=640,y=360,firstFrame=0),interpolation='hold'),key(96,dict(x=480,y=403,scaleX=1.25,scaleY=1.25),interpolation='hold'),key(192,dict(x=640,y=360,scaleX=1,scaleY=1),interpolation='hold'),key(304,dict(x=462,y=390,scaleX=1.28,scaleY=1.28),interpolation='hold'),key(492,dict(x=640,y=360,scaleX=1,scaleY=1),interpolation='hold')],playback='play once',sync_to_timeline=True)
        self.animate([camera])
        self.upload_chime()
        graph=self.call('get_symbol_graph',self.scope)
        if graph.get('cycles'):raise RuntimeError('Unexpected symbol dependency cycle')
        self.edit('save_project',{})
        movie=self.call('export_movie',{**self.scope,'start_frame':0,'end_frame':575,'audio':True})
        self.call('review_frames',dict(run_id=movie['run_id'],indices=[0,48,96,144,192,218,252,312,336,408,465,504,548,575]))
        final=self.call('get_documents')
        existing={d['document_id']:d for d in final}
        if any(existing.get(d['document_id'])!=d for d in baseline):raise RuntimeError('An existing document changed; inspect immediately')
        print(json.dumps(dict(project=created,movie=movie,report=str(self.checkpoint)),ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',type=Path,required=True);args=parser.parse_args()
    os.umask(0o077);report=args.report_dir.resolve();report.mkdir(mode=0o700,parents=True,exist_ok=False)
    demo=Demo(report)
    try:demo.build()
    finally:demo.client.close()

if __name__=='__main__':main()
