'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../cep/com.mikechambers.an/animation-host.js'),'utf8');
function harness(){
    const state={backups:0,edits:0,bytes:100,failBackup:false,active:null},files=new Map();
    const symbol={name:'Head',itemType:'graphic',timeline:{frameCount:4,layers:[],currentFrame:0,currentLayer:0}};
    const element=()=>({name:'head',elementType:'instance',instanceType:'symbol',symbolType:'graphic',libraryItem:symbol,matrix:{a:1,b:0,c:0,d:1,tx:20,ty:30},firstFrame:0,colorAlphaPercent:100,getTransformationPoint:()=>({x:3,y:4})});
    const first={startFrame:0,duration:8,elements:[element()],tweenType:'none'},layer={name:'Head',layerType:'normal',visible:true,locked:false,frames:Array(8).fill(first)};
    const timeline={frameCount:8,currentFrame:3,currentLayer:0,layers:[layer],insertKeyframe(f){state.edits++;const e={...layer.frames[f].elements[0],matrix:{...layer.frames[f].elements[0].matrix}};layer.frames[f]={startFrame:f,duration:1,elements:[e],tweenType:'none'};}};
    const doc={id:11,width:1280,height:720,frameRate:24,currentTimeline:0,pathURI:'file:///private/managed/project.fla',selection:[],library:{items:[symbol]},getTimeline:()=>timeline,selectNone(){this.selection=[];},saveAsCopy(uri){state.backups++;if(state.failBackup)return false;files.set(uri,state.bytes);return true;}};
    const other={id:12};state.active=other;
    const ctx=vm.createContext({fl:{documents:[doc,other],getDocumentDOM:()=>state.active,setActiveWindow:d=>{state.active=d;}},FLfile:{exists:p=>files.has(p),getSize:p=>{if(p.endsWith('/backup.fla')){state.backups++;return state.failBackup?0:state.bytes;}return files.get(p);},copy:(a,b)=>{if(!files.has(a)||files.has(b))return false;files.set(b,files.get(a));return true;}}});
    vm.runInContext(source,ctx);
    const scope={document_id:11,project_run_id:'run-'+'a'.repeat(32),timeline_index:0,layers:['Head'],start_frame:0,end_frame:7,symbol_name:null};
    function run(action,extra={}){const packet={action,expires_at:Date.now()+10000,options:{...scope,managed_project_uri:doc.pathURI,output_uri:'file:///private/new/',...extra}};return JSON.parse(vm.runInContext('runAnimationHost('+JSON.stringify(packet)+')',ctx));}
    function edit(extra={}){const inspected=run('inspectAnimation');assert.equal(inspected.ok,true);files.set('file:///private/new/backup.fla',state.bytes);return {...extra,inspection_scope:scope,expected_state:inspected.data.state_json,backup_prepared:true};}
    const poses=[{layer:'Head',instance:'head',frame:4,matrix:{a:.9,b:.1,c:-.2,d:1.1,tx:100,ty:120},alpha:80,firstFrame:2}];
    return {state,files,doc,other,timeline,layer,symbol,run,edit,poses,scope,ctx};
}
test('inspection captures full matrices, pivots, discrete poses and restores focus/playhead',()=>{
    const h=harness(),r=h.run('inspectAnimation');assert.equal(r.ok,true);const e=r.data.state.layers[0].keyframes[0].elements[0];
    assert.deepEqual(e.matrix,{a:1,b:0,c:0,d:1,tx:20,ty:30});assert.deepEqual(e.pivot,{x:3,y:4});assert.equal(e.firstFrame,0);
    assert.equal(h.state.active,h.other);assert.equal(h.timeline.currentFrame,3);assert.equal(h.state.backups,0);
});
test('a guarded pose gets a backup, exact matrix readback and native key',()=>{
    const h=harness(),r=h.run('applyPoses',h.edit({poses:h.poses}));assert.equal(r.ok,true);assert.equal(r.data.readback_verified,true);assert.equal(r.data.max_matrix_error,0);
    assert.equal(h.state.backups,1);assert.equal(h.state.edits,1);assert.deepEqual(JSON.parse(JSON.stringify(h.layer.frames[4].elements[0].matrix)),h.poses[0].matrix);
    assert.equal(h.state.active,h.other);assert.equal(h.timeline.currentFrame,3);
});
test('wrong managed file, stale revision, locked layer and out-of-scope poses prevent all writes',()=>{
    for(const setup of [h=>{h.doc.pathURI='file:///user/important.fla';},h=>{h.layer.frames[0].elements[0].matrix.tx=21;},h=>{h.layer.locked=true;},h=>{h.poses[0].layer='Other';},h=>{h.poses[0].firstFrame=4;}]){
        const h=harness(),opts=h.edit({poses:h.poses});setup(h);if(h.doc.pathURI.includes('important'))opts.managed_project_uri='file:///private/managed/project.fla';
        const r=h.run('applyPoses',opts);assert.equal(r.ok,false);assert.equal(h.state.backups,0);assert.equal(h.state.edits,0);assert.equal(h.state.active,h.other);
    }
});
test('failed and empty backups prevent pose mutations',()=>{
    for(const setup of [h=>h.state.failBackup=true,h=>h.state.bytes=0]){const h=harness(),opts=h.edit({poses:h.poses});setup(h);assert.equal(h.run('applyPoses',opts).ok,false);assert.equal(h.state.edits,0);}
});
test('native rounding outside tolerance is reported with backup and no automatic replay',()=>{
    const h=harness(),opts=h.edit({poses:h.poses});const original=h.timeline.insertKeyframe;
    h.timeline.insertKeyframe=function(f){original.call(this,f);let value=h.layer.frames[f].elements[0].matrix;Object.defineProperty(h.layer.frames[f].elements[0],'matrix',{get:()=>value,set:m=>{value={...m,tx:m.tx+1};}});};
    const r=h.run('applyPoses',opts);assert.equal(r.ok,false);assert.match(r.error,/readback/);assert.match(r.error,/backup exists/);assert.equal(h.state.edits,1);
});
test('symbol graph reports dependency cycles and independent MovieClip timing',()=>{
    const h=harness();h.symbol.itemType='movie clip';h.symbol.timeline.layers=[{frames:[{startFrame:0,elements:[{libraryItem:h.symbol}]}]}];
    const r=h.run('inspectGraph');assert.equal(r.ok,true);assert.deepEqual(r.data.cycles,[['Head','Head']]);assert.equal(r.data.runtime_warnings.length,1);
});
test('active nested editing cannot redirect a root edit',()=>{
    const h=harness(),opts=h.edit({poses:h.poses});h.timeline.libraryItem=h.symbol;assert.equal(h.run('applyPoses',opts).ok,false);assert.equal(h.state.backups,0);
});
test('Mac platform path is checked exactly when Animate uses a different URI representation',()=>{
    const h=harness();h.doc.pathURI='file:///managed/project.fla';h.doc.path='/private/managed/project.fla';
    assert.equal(h.run('inspectAnimation',{managed_project_uri:'file:///private/managed/project.fla',managed_project_path:h.doc.path}).ok,true);
    assert.equal(h.run('inspectAnimation',{managed_project_uri:'file:///wrong/project.fla',managed_project_path:'/user/important.fla'}).ok,false);
});

test('saving retains a separate backup even if Animate consumes its last saveAsCopy file',()=>{
    const h=harness();h.doc.saveAsCopy=(uri)=>{h.files.set(uri,100);h.state.lastCopy=uri;return true;};
    const contextSave=(doc,uri)=>{h.files.delete(h.state.lastCopy);return true;};
    // The harness exposes its native fl object for this save bookkeeping regression.
    h.ctx.fl.saveDocument=contextSave;
    const opts=h.edit();const prepared=h.run('prepareBackup',opts);assert.equal(prepared.ok,true);assert.equal(prepared.data.snapshot_prepared,true);h.files.set('file:///private/new/backup.fla',h.files.get(h.state.lastCopy));const r=h.run('saveProject',opts);assert.equal(r.ok,true);assert.equal(h.files.get('file:///private/new/backup.fla'),100);
});
test('native text attributes apply without relying on addNewText selection',()=>{
    const h=harness();let editing=null,created=null;
    h.doc.getTimeline=()=>editing||h.timeline;
    h.doc.library.addNewItem=(kind,name)=>{h.doc.library.items.push({name,itemType:kind,timeline:{frameCount:1,currentFrame:0,currentLayer:0,layers:[{frames:[{elements:[]}]}]}});return true;};
    h.doc.library.editItem=name=>{editing=h.doc.library.items.find(x=>x.name===name).timeline;return true;};
    h.doc.exitEditMode=()=>{editing=null;};
    h.doc.getCustomFill=()=>({});h.doc.getCustomStroke=()=>({});h.doc.setCustomFill=()=>{};h.doc.setCustomStroke=()=>{};
    h.doc.addNewText=(bounds,text)=>{const attrs={size:12,bold:false};created={elementType:'text',getTextString:()=>text,setTextAttr:(k,v)=>{attrs[k]=v;},getTextAttr:k=>attrs[k]};editing.layers[0].frames[0].elements.push(created);h.doc.selection=[];};
    const primitive={type:'text',bounds:{left:0,top:0,right:300,bottom:70},text:'Readable text',font_size:32,bold:true,fill:'#333333'};
    const r=h.run('authorScene',h.edit({frame_count:8,symbols:[{name:'Caption',frames:[[primitive]]}],instances:[]}));
    assert.equal(r.ok,true);assert.equal(created.getTextAttr('size'),32);assert.equal(created.getTextAttr('face'),'Arial');assert.equal(created.getTextAttr('bold'),true);
});
