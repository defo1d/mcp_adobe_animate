import zipfile
import io
import struct
import base64
import concurrent.futures
import copy
import io
import json
import math
import os
from pathlib import Path
import sys
import unittest
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp'))
from motion import compile_motion, evaluate, matrix, multiply, retime_motion, solve_two_bone, validate_tracks
from animation_tools import validate_art
from audio import begin, append, finalize, inspect_pcm, add_cue, read_cues
from review import sampled_pixels, review, export_movie
from preview import create_job, finish_frames
from bridge import Broker
from test_safe import LocalTest, png
from config import load_config

def track(keys, **extra):
    return dict(layer='head',instance='head',keys=[dict(frame=f,values=v,**options) for f,v,options in keys],**extra)

class MotionTests(unittest.TestCase):
    def test_timing_solves_bezier_x_and_keeps_offgrid_keys(self):
        t=track([(0,dict(x=0,y=0),dict(easing=[.9,0,1,1])),(7,dict(x=100),{})])
        self.assertLess(evaluate(t,3.5)['x'],25)
        result=compile_motion([t],2)
        self.assertEqual([p['frame'] for p in result['poses']],[0,2,4,6,7])
        self.assertEqual(result['poses'][-1]['matrix']['tx'],100)
    def test_spatial_arc_and_discrete_mouth(self):
        t=track([(0,dict(x=0,y=0,firstFrame=2),dict(path=[dict(x=0,y=100),dict(x=100,y=100)])),(10,dict(x=100,y=0,firstFrame=3),{})])
        self.assertAlmostEqual(evaluate(t,5)['y'],75)
        self.assertEqual(evaluate(t,9)['firstFrame'],2)
        self.assertEqual(evaluate(t,10)['firstFrame'],3)
    def test_hold_and_overshoot(self):
        t=track([(0,dict(x=0,y=0),dict(interpolation='hold')),(10,dict(x=100),{})])
        self.assertEqual(evaluate(t,9)['x'],0)
        t['keys'][0]=dict(frame=0,values=dict(x=0,y=0,alpha=90),easing='back_out')
        t['keys'][1]['values']['alpha']=100
        self.assertGreater(evaluate(t,7)['x'],100)
        self.assertEqual(evaluate(t,7)['alpha'],100)
    def test_rotation_preserves_full_turn_or_shortest(self):
        t=track([(0,dict(x=0,y=0,rotation=350),{}),(10,dict(rotation=10),{})])
        self.assertEqual(evaluate(t,5)['rotation'],180)
        t['rotation_mode']='shortest'
        self.assertEqual(evaluate(t,5)['rotation'],360)
        t['keys'][0]['values']['rotation']=0;t['keys'][1]['values']['rotation']=720;t['rotation_mode']='explicit'
        self.assertEqual(evaluate(t,5)['rotation'],360)
    def test_local_pivot_and_nonuniform_parent_matrix(self):
        parent=track([(0,dict(x=50,y=60,rotation=30,scaleX=2,scaleY=.5,alpha=50),{})])
        child=track([(0,dict(x=10,y=20,rotation=40,alpha=80),{})],parent=0,pivot=dict(x=3,y=4));child['layer']='hand';child['instance']='hand'
        actual=compile_motion([parent,child])['poses'][1]
        expected=multiply(matrix(evaluate(parent,0),dict(x=0,y=0)),matrix(evaluate(child,0),child['pivot']))
        for k,v in expected.items():self.assertAlmostEqual(actual['matrix'][k],v,places=7)
        self.assertEqual(actual['alpha'],40)
    def test_ancestor_key_is_sampled_in_child(self):
        parent=track([(0,dict(x=0,y=0),{}),(3,dict(x=20),{}),(8,dict(x=30),{})])
        child=track([(0,dict(x=10,y=10),{}),(8,dict(x=10),{})],parent=0);child['layer']='hand';child['instance']='hand'
        self.assertIn(3,[p['frame'] for p in compile_motion([parent,child],2)['poses'] if p['layer']=='hand'])
    def test_invalid_cycles_nan_budget_and_collapsed_retime(self):
        t=track([(0,dict(x=0,y=0),{}),(1000,dict(x=100),{})])
        for bad in [dict(t,parent=0),dict(t,keys=[dict(frame=0,values=dict(x=math.nan,y=0))])]:
            with self.assertRaises(ValueError): validate_tracks([bad])
        with self.assertRaises(ValueError): compile_motion([t],1)
        t['keys'].insert(1,dict(frame=1,values=dict(x=1)))
        with self.assertRaises(ValueError):retime_motion([t],0,1)
    def test_retime_is_global_and_does_not_mutate_source(self):
        t=track([(10,dict(x=0,y=0),{}),(20,dict(x=100),{})]);before=copy.deepcopy(t)
        self.assertEqual([p['frame'] for p in retime_motion([t],100,140)['tracks'][0]['keys']],[100,140])
        self.assertEqual(t,before)
    def test_synced_nested_graphic_keeps_phase_across_baked_keys(self):
        t=track([(100,dict(x=0,y=0,firstFrame=100),{}),(110,dict(x=20),{})],playback='play once',sync_to_timeline=True)
        poses=compile_motion([t],2)['poses']
        self.assertEqual([p['firstFrame'] for p in poses],[100,102,104,106,108,110])
        self.assertTrue(all(p['loop']=='play once' for p in poses))
        t['keys'][1]['values']['firstFrame']=0
        with self.assertRaises(ValueError):compile_motion([t])
    def test_ik_lengths_reach_and_bend(self):
        for bend in (-1,1):
            r=solve_two_bone(dict(x=0,y=0),dict(x=6,y=0),4,4,bend)
            self.assertTrue(r['reachable']);self.assertLess(r['target_error'],1e-8)
            self.assertAlmostEqual(math.hypot(r['elbow']['x'],r['elbow']['y']),4)
            self.assertEqual(1 if r['elbow']['y']>0 else -1,bend)
        r=solve_two_bone(dict(x=0,y=0),dict(x=20,y=0),4,4)
        self.assertFalse(r['reachable']);self.assertAlmostEqual(r['target_error'],12)

class AnimationFilesTests(LocalTest):
    def wav(self):
        output=io.BytesIO()
        with wave.open(output,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\x00\x00'*800)
        return output.getvalue()
    def upload(self):
        data=self.wav();run=begin(self.config,len(data))['run_id']
        append(self.config,run,0,base64.b64encode(data).decode())
        return run
    def test_pcm_validated_and_finalized_is_immutable(self):
        run=self.upload();r=finalize(self.config,run);self.assertEqual(r['duration'],.1)
        self.assertEqual(finalize(self.config,run),r)
        with self.assertRaises(ValueError):append(self.config,run,len(self.wav()),'AAAA')
        path=Path(self.config['output_dir'])/run/'audio.wav';raw=bytearray(path.read_bytes());raw[-1]=1;path.write_bytes(raw)
        with self.assertRaises(ValueError):finalize(self.config,run)
    def test_pcm_rejects_partial_compressed_and_oversized(self):
        data=self.wav();compressed=bytearray(data);compressed[20]=3
        for bad in [data[:-1],bytes(compressed),b'RIFF'+b'\x00'*100]:
            with self.assertRaises(ValueError):inspect_pcm(bad)
    def test_parallel_append_has_one_winner(self):
        data=self.wav();run=begin(self.config,len(data))['run_id'];encoded=base64.b64encode(data).decode()
        def write():
            try:append(self.config,run,0,encoded);return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool: self.assertEqual(list(pool.map(lambda _:write(),range(2))).count(True),1)
        self.assertEqual(finalize(self.config,run)['frame_count'],800)
    def test_metadata_symlink_never_overwrites_target(self):
        run=self.upload();job=Path(self.config['output_dir'])/run;target=self.root/'untouched';target.write_text('original')
        (job/'audio.json').unlink();(job/'audio.json').symlink_to(target)
        with self.assertRaises(OSError):finalize(self.config,run)
        self.assertEqual(target.read_text(),'original')
    def test_cue_record_symlink_and_duplicate_rejected(self):
        job=create_job(self.config);project=job/'project.fla';project.write_bytes(b'fla')
        cue=dict(audio_run_id='run-'+'a'*32,layer='voice',start_frame=0,sound_name='audio.wav')
        add_cue(project,cue);self.assertEqual(read_cues(project),[cue])
        with self.assertRaises(ValueError):add_cue(project,cue)
        target=self.root/'untouched';target.write_text('original');(job/'audio-cues.json').unlink();(job/'audio-cues.json').symlink_to(target)
        with self.assertRaises(OSError):add_cue(project,cue)
        self.assertEqual(target.read_text(),'original')
    def test_render_review_separates_hold_from_blank(self):
        job=create_job(self.config)
        for i,c in enumerate([(220,80,70,255),(220,80,70,255),(0,0,0,0)]): (job/('frame-%06d.png'%(i+1))).write_bytes(png(color=c))
        finish_frames(self.config,job,dict(start_frame=0,end_frame=2,step=1,document_id=1,timeline_index=0),dict(frame_rate=24))
        result=review(self.config,job.name,[0,1,2]);self.assertTrue(Path(result['contact_sheet']).is_file())
        self.assertEqual([w['kind'] for w in result['warnings']],['identical_sample','fully_transparent_render'])
    def test_decompression_bomb_rejected(self):
        data=png(width=17,height=17)
        with self.assertRaises(ValueError):sampled_pixels(data,(16,16))
    def test_closed_art_schema_rejects_code_paths_and_invisible_shapes(self):
        valid=dict(name='head',frames=[[dict(type='ellipse',bounds=dict(left=0,top=0,right=20,bottom=20),fill='#ffffff')]])
        validate_art([valid],[])
        for bad in [dict(valid,name='../head'),dict(valid,script='injected'),dict(name='head',frames=[[dict(type='path',commands=[{}],stroke='#000000')]]),dict(name='head',frames=[[dict(type='ellipse',bounds=dict(left=0,top=0,right=20,bottom=20))]])]:
            with self.assertRaises(ValueError):validate_art([bad],[])
    def test_long_movie_crosses_batch_boundary_and_encodes_recorded_pcm(self):
        executable=os.environ.get('ANIMATE_TEST_FFMPEG')
        if not executable:self.skipTest('Set ANIMATE_TEST_FFMPEG to test the real encoder')
        self.data['ffmpeg_path']=executable;self.filename.write_text(json.dumps(self.data));config=load_config(str(self.filename))
        project=create_job(config);(project/'project.fla').write_bytes(b'new managed fixture');(project/'project.json').write_text(json.dumps(dict(kind='animate-mcp-project-v1',file='project.fla')))
        audio=self.upload();finalize(config,audio)
        cue=dict(audio_run_id=audio,layer='voice',start_frame=3,sound_name='audio.wav');add_cue(project/'project.fla',cue)
        batches=[]
        def request(config,action,args):
            if action=='inspectAnimation':
                layers=[] if not args['layers'] else [dict(keyframes=[dict(frame=3,sound='audio.wav',sound_sync='stream',sound_loop=1)])]
                return dict(state=dict(frame_rate=24,frame_count=261,width=16,height=16,layers=layers))
            self.assertEqual(action,'exportManagedFrames');self.assertEqual(args['project_run_id'],project.name)
            batches.append((args['start_frame'],args['end_frame']));job=create_job(config)
            for i,frame in enumerate(range(args['start_frame'],args['end_frame']+1)):(job/('frame-%06d.png'%(i+1))).write_bytes(png(color=(frame%256,80,70,255)))
            return finish_frames(config,job,args,dict(frame_rate=24))
        result=export_movie(config,dict(document_id=7,project_run_id=project.name,timeline_index=0,start_frame=0,end_frame=260),request)
        self.assertEqual(batches,[(0,239),(240,260)]);self.assertEqual(result['frame_count'],261)
        self.assertAlmostEqual(result['duration_seconds'],261/24);self.assertTrue(result['audio']);self.assertEqual(result['audio_cue_count'],1)
        self.assertGreater(Path(result['mp4']).stat().st_size,1000)
        self.assertEqual(len(json.loads(Path(result['manifest']).read_text())['frames']),261)
        self.assertIn('<video',Path(result['preview_html']).read_text())
    def test_inspection_revisions_are_bound_and_single_use(self):
        from urllib.parse import urlparse,unquote
        broker=Broker(self.config);session='d'*32;broker.register(session)
        project=create_job(self.config);(project/'project.fla').write_bytes(b'fla');(project/'project.json').write_text(json.dumps(dict(kind='animate-mcp-project-v1',file='project.fla')))
        scope=dict(document_id=7,project_run_id=project.name,timeline_index=0,layers=[],start_frame=0,end_frame=0,symbol_name=None)
        def exchange(action,args,data):
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                result=pool.submit(broker.command,action,args);packet=broker.next(session)
                self.assertEqual(packet['options']['managed_project_path'],str(project/'project.fla'))
                if action=='saveProject':
                    self.assertEqual(packet['action'],'prepareBackup')
                    folder=Path(unquote(urlparse(packet['options']['output_uri']).path))
                    with zipfile.ZipFile(folder/'snapshot.fla','w',compression=zipfile.ZIP_DEFLATED) as archive: archive.writestr('DOMDocument.xml','<DOMDocument/>')
                    broker.response(session,packet['id'],dict(ok=True,data={'snapshot_prepared':True}))
                    packet=broker.next(session)
                    self.assertEqual(packet['action'],'saveProject');self.assertTrue(packet['options']['backup_prepared'])
                    self.assertTrue((folder/'backup.fla').is_file())
                broker.response(session,packet['id'],dict(ok=True,data=data));return result.result(timeout=2)
        state=dict(document_id=7)
        inspected=exchange('inspectAnimation',scope,dict(state=state,state_json=json.dumps(state)))
        edit={k:scope[k] for k in ('document_id','project_run_id','timeline_index')};edit['revision_id']=inspected['revision_id']
        saved=exchange('saveProject',edit,dict(saved=True));self.assertTrue(Path(saved['backup']).is_file())
        with self.assertRaisesRegex(ValueError,'consumed'):broker.command('saveProject',edit)
        self.assertTrue(broker.commands.empty())
    def test_review_reports_transparency_coverage(self):
        from review import sampled_pixels
        self.assertEqual(sampled_pixels(png(color=(80,40,20,0)),(16,16))['transparent_sample_fraction'],1)
        self.assertEqual(sampled_pixels(png(color=(80,40,20,255)),(16,16))['transparent_sample_fraction'],0)
    def test_fla_snapshot_completion_and_adobe_directory_size(self):
        from backup import validate_fla, preserve_snapshot
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive: archive.writestr('DOMDocument.xml','<DOMDocument/>')
        data=output.getvalue();self.assertEqual(len(validate_fla(data)),64)
        with self.assertRaises(ValueError):validate_fla(data[:-22])
        # Animate 2024 emits a central size 54 bytes larger than actual data.
        view=bytearray(data);end=len(view)-22;size=struct.unpack_from('<I',view,end+12)[0];struct.pack_into('<I',view,end+12,size+54)
        self.assertEqual(len(validate_fla(view)),64)
        job=create_job(self.config);(job/'snapshot.fla').write_bytes(view)
        preserve_snapshot(job);self.assertEqual((job/'backup.fla').read_bytes(),view)
        self.assertEqual((job/'backup.fla').stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):preserve_snapshot(job)
    def test_native_snapshot_requires_document_and_archive_integrity(self):
        from backup import validate_fla
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('other.xml','not a document')
        with self.assertRaises(ValueError):validate_fla(output.getvalue())
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('DOMDocument.xml','<DOMDocument/>')
        damaged=bytearray(output.getvalue());damaged[damaged.index(b'<DOMDocument/>')]=0
        with self.assertRaises(ValueError):validate_fla(damaged)
    def test_legacy_mutations_are_rejected_before_any_panel_work(self):
        broker=Broker(self.config)
        args=dict(document_id=7,timeline_index=0,operations=[dict(type='pose',layer=0,frame=0,instance='head',values=dict(x=20))])
        with self.assertRaisesRegex(ValueError,'Legacy'):broker.command('applyAnimation',args)
        self.assertTrue(broker.commands.empty())
    def test_panel_disconnect_invalidates_all_inspection_revisions(self):
        broker=Broker(self.config);broker.register('d'*32);broker.revisions['e'*32]=dict(created=0)
        broker.disconnect('d'*32);self.assertEqual(broker.revisions,{})

if __name__=='__main__':unittest.main()
