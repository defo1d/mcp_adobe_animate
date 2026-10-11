/* Fixed ES5 authoring/inspection code, serialized into Animate's native JSFL.
 * Only validated data is supplied. All new writes require a matching managed
 * FLA, an exact scoped state guard and a nonempty backup before any edit.
 */
'use strict';
function runAnimationHost(packet) {
    function quote(s) { return '"'+String(s).replace(/[\\"\x00-\x1f\x7f-\uffff]/g,function(c){return '\\u'+('0000'+c.charCodeAt(0).toString(16)).slice(-4);})+'"'; }
    function encode(v) {
        if(v===null || v===undefined)return 'null';
        if(typeof v==='string')return quote(v);
        if(typeof v==='number')return isFinite(v)?String(v):'null';
        if(typeof v==='boolean')return String(v);
        var a=[],k,i;
        if(v instanceof Array){for(i=0;i<v.length;i++)a.push(encode(v[i]));return '['+a.join(',')+']';}
        for(k in v)if(Object.prototype.hasOwnProperty.call(v,k))a.push(quote(k)+':'+encode(v[k]));
        return '{'+a.join(',')+'}';
    }
    function need(value,message){if(!value)throw new Error(message);}
    function short(s){return String(s||'').slice(0,128);}
    function contains(a,value){for(var i=0;i<a.length;i++)if(a[i]===value)return true;return false;}
    function alive(){need((new Date()).getTime()<packet.expires_at,'Request expired; inspect state before retrying');}
    function optional(o,k){try {var v=o[k];return typeof v==='number'&&isFinite(v)?v:(typeof v==='string'?short(v):null);}catch(_){return null;}}
    var doc=null, root=null, target=null, oldDoc=null, oldFrame=null, oldLayer=null, oldSelection=null;
    var entered=false, targetFrame=null,targetLayer=null,oldFill=null,oldStroke=null,backup=null,applied=0;
    var opts=packet.options;
    function libraryItem(name){var result=null;for(var i=0;i<doc.library.items.length;i++)if(doc.library.items[i].name===name){need(result===null,'Duplicate library identity');result=doc.library.items[i];}return result;}
    function layerIndex(timeline,name){var found=-1;for(var i=0;i<timeline.layers.length;i++)if(timeline.layers[i].name===name){need(found===-1,'Duplicate layer name: '+name);found=i;}need(found>=0,'Missing layer: '+name);return found;}
    function named(timeline,name,instance,frame){
        var layer=timeline.layers[layerIndex(timeline,name)];need(!layer.locked,'Layer is locked: '+name);
        need(frame<layer.frames.length,'Frame outside layer');var result=null,elements=layer.frames[frame].elements;
        for(var i=0;i<elements.length;i++)if(elements[i].name===instance){need(result===null,'Duplicate instance name');result=elements[i];}
        need(result&&result.elementType==='instance'&&result.instanceType==='symbol','Named symbol is missing');
        need(result.symbolType==='graphic','Sampled poses require a graphic symbol for deterministic previews');return result;
    }
    function targetTimeline(symbol){
        if(symbol===null || symbol===undefined)return root;
        var item=libraryItem(symbol);need(item&&(item.itemType==='graphic'||item.itemType==='movie clip'),'Missing symbol timeline');return item.timeline;
    }
    function references(item,name,seen,budget){
        if(item.name===name)return true;
        if(seen['$'+item.name]||!item.timeline)return false;
        seen['$'+item.name]=true;var t=item.timeline;
        for(var l=0;l<t.layers.length;l++)for(var f=0;f<t.layers[l].frames.length;f++){
            need(++budget.count<=500000,'Dependency preflight exceeds scan budget');
            var frame=t.layers[l].frames[f];if(frame.startFrame!==f)continue;
            for(var e=0;e<frame.elements.length;e++)if(frame.elements[e].libraryItem&&references(frame.elements[e].libraryItem,name,seen,budget))return true;
        }
        return false;
    }
    function verifyMatrix(actual,expected){
        var maximum=0;for(var property in expected){var error=Math.abs(actual[property]-expected[property]);need(isFinite(error)&&error<=(property==='tx'||property==='ty'?.051:.0002),'Pose matrix readback differs from requested value');maximum=Math.max(maximum,error);}return maximum;
    }
    function elementRecord(el){
        var r={name:short(el.name),type:short(el.elementType),instance_type:short(el.instanceType),symbol_type:short(el.symbolType)};
        var properties=['x','y','width','height','rotation','scaleX','scaleY','skewX','skewY','firstFrame','lastFrame','loop','colorMode','colorAlphaPercent','left','top'];
        for(var i=0;i<properties.length;i++)r[properties[i]]=optional(el,properties[i]);
        if(el.libraryItem){r.symbol=short(el.libraryItem.name);r.symbol_frames=el.libraryItem.timeline?el.libraryItem.timeline.frameCount:null;}
        var m=el.matrix;r.matrix=m?{a:m.a,b:m.b,c:m.c,d:m.d,tx:m.tx,ty:m.ty}:null;
        try {var p=el.getTransformationPoint();r.pivot={x:p.x,y:p.y};}catch(_){r.pivot=null;}
        if(el.elementType==='shape'){r.edge_count=el.edges?el.edges.length:null;r.contour_count=el.contours?el.contours.length:null;}
        return r;
    }
    function capture(scope,timeline){
        need(timeline.frameCount<=10000&&timeline.layers.length<=200,'Timeline exceeds bounds');
        var state={document_id:doc.id,timeline_index:doc.currentTimeline,symbol_name:scope.symbol_name,
            width:doc.width,height:doc.height,frame_rate:doc.frameRate,frame_count:timeline.frameCount,
            start_frame:scope.start_frame,end_frame:scope.end_frame,layer_metadata:[],library:[],layers:[],
            value_semantics:'Authoring keyframe properties; rendered PNGs are authoritative for interpolated and nested appearance'};
        var i,j,k;
        for(i=0;i<timeline.layers.length;i++)state.layer_metadata.push({index:i,name:short(timeline.layers[i].name),type:short(timeline.layers[i].layerType),locked:!!timeline.layers[i].locked,visible:!!timeline.layers[i].visible,frame_count:timeline.layers[i].frames.length});
        need(doc.library.items.length<=1024,'Library exceeds bounds');
        for(i=0;i<doc.library.items.length;i++){var item=doc.library.items[i];state.library.push({name:short(item.name),type:short(item.itemType),frame_count:item.timeline?item.timeline.frameCount:null});}
        for(i=0;i<scope.layers.length;i++){
            var index=layerIndex(timeline,scope.layers[i]),layer=timeline.layers[index];
            var record={index:index,name:short(layer.name),keyframes:[]};
            for(j=0;j<layer.frames.length;j++){
                var frame=layer.frames[j];if(frame.startFrame!==j||j>scope.end_frame||j+frame.duration<=scope.start_frame)continue;
                need(frame.elements.length<=64,'Too many elements; narrow the inspection scope');
                var entry={frame:j,duration:frame.duration,label:short(frame.name),label_type:short(frame.labelType),tween:short(frame.tweenType),easing:optional(frame,'tweenEasing'),sound:frame.soundLibraryItem?short(frame.soundLibraryItem.name):null,sound_sync:short(frame.soundSync),sound_loop:optional(frame,'soundLoop'),elements:[]};
                if(frame.hasCustomEase){try {entry.custom_ease=frame.getCustomEase('all');}catch(_){entry.custom_ease=null;}}
                for(k=0;k<frame.elements.length;k++)entry.elements.push(elementRecord(frame.elements[k]));
                record.keyframes.push(entry);need(record.keyframes.length<=512,'Inspection has too many keys');
            }
            state.layers.push(record);
        }
        var serialized=encode(state);need(serialized.length<=48000,'Inspection too large; request fewer layers or a shorter span');
        return {state:state,state_json:serialized};
    }
    function backedUp(){
        backup=opts.output_uri+'backup.fla';
        need(opts.backup_prepared===true&&FLfile.exists(backup)&&Number(FLfile.getSize(backup))>0,'Verified durable backup required; no edits applied');
    }
    function draw(p){
        alive();doc.selectNone();
        var fill=doc.getCustomFill('toolbar');fill.style='solid';fill.color=p.fill||'#000000';doc.setCustomFill(fill);
        var stroke=doc.getCustomStroke('toolbar');stroke.style='solid';stroke.color=p.stroke||'#000000';stroke.thickness=p.stroke_width===undefined?1:p.stroke_width;doc.setCustomStroke(stroke);
        if(p.type==='rect')doc.addNewRectangle(p.bounds,0,p.fill===null||p.fill===undefined,p.stroke===null||p.stroke===undefined);
        else if(p.type==='ellipse')doc.addNewOval(p.bounds,p.fill===null||p.fill===undefined,p.stroke===null||p.stroke===undefined);
        else if(p.type==='text'){
            doc.addNewText(p.bounds,p.text);
            var textTimeline=doc.getTimeline(),textElements=textTimeline.layers[textTimeline.currentLayer].frames[textTimeline.currentFrame].elements,field=null;
            for(var te=0;te<textElements.length;te++)if(textElements[te].elementType==='text')field=textElements[te];
            need(field&&field.getTextString()===p.text,'New text field could not be identified');
            // addNewText(bounds,text) does not reliably select its new field.
            // Address the native Text object directly instead of toolbar selection.
            field.setTextAttr('face','Arial');field.setTextAttr('size',p.font_size);
            field.setTextAttr('bold',p.bold);field.setTextAttr('fillColor',p.fill||p.stroke||'#000000');
            need(field.getTextAttr('size')===p.font_size&&field.getTextAttr('bold')===p.bold,'Text style readback differs');
        }else{
            var path=fl.drawingLayer.newPath(),x=0,y=0,startX=0,startY=0;
            for(var j=0;j<p.commands.length;j++){
                var c=p.commands[j];
                if(c[0]==='M'){if(j>0)path.newContour();path.addPoint(c[1],c[2]);x=c[1];y=c[2];startX=x;startY=y;}
                else if(c[0]==='L'){path.addPoint(c[1],c[2]);x=c[1];y=c[2];}
                else if(c[0]==='Q'){path.addCurve(x,y,c[1],c[2],c[3],c[4]);x=c[3];y=c[4];}
                else if(c[0]==='C'){path.addCubicCurve(x,y,c[1],c[2],c[3],c[4],c[5],c[6]);x=c[5];y=c[6];}
                else if(c[0]==='Z'){path.close();x=startX;y=startY;}
            }
            path.makeShape(p.fill===null||p.fill===undefined,p.stroke===null||p.stroke===undefined);
        }
        doc.selectNone();
    }
    try{
        alive();var documents=fl.documents;for(var d=0;d<documents.length;d++)if(documents[d].id===opts.document_id){doc=documents[d];break;}
        need(doc,'Pinned document is closed');need((typeof opts.managed_project_uri==='string'&&doc.pathURI===opts.managed_project_uri)||(typeof opts.managed_project_path==='string'&&opts.managed_project_path.length>0&&doc.path===opts.managed_project_path),'Only the matching MCP-created FLA is allowed');
        oldDoc=fl.getDocumentDOM();fl.setActiveWindow(doc);root=doc.getTimeline();
        need(doc.currentTimeline===opts.timeline_index&&!root.libraryItem,'Scene changed or symbol editing is active; return to the root scene');
        oldFrame=root.currentFrame;oldLayer=root.currentLayer;oldSelection=doc.selection;
        var scope=packet.action==='inspectAnimation'?opts:opts.inspection_scope;
        if(packet.action==='inspectGraph'){
            var graph={symbols:[],runtime_warnings:[],cycles:[],truncated:false},visitedFrames=0;
            for(var g=0;g<doc.library.items.length;g++){
                alive();
                var symbol=doc.library.items[g];if(!symbol.timeline)continue;
                need(graph.symbols.length<128,'Symbol graph exceeds 128 items');var timeline=symbol.timeline,deps=[],seen={};
                for(var l=0;l<timeline.layers.length;l++)for(var f=0;f<timeline.layers[l].frames.length;f++){
                    need(++visitedFrames<=500000,'Symbol graph exceeds scan budget');
                    var gf=timeline.layers[l].frames[f];if(gf.startFrame!==f)continue;
                    for(var e=0;e<gf.elements.length;e++)if(gf.elements[e].libraryItem){var dep=short(gf.elements[e].libraryItem.name);if(!seen['$'+dep]){seen['$'+dep]=true;deps.push(dep);}}
                }
                graph.symbols.push({name:short(symbol.name),type:short(symbol.itemType),frame_count:timeline.frameCount,dependencies:deps});
                if(symbol.itemType==='movie clip')graph.runtime_warnings.push(short(symbol.name)+': independent runtime playback is not evaluated by PNG exports');
            }
            var graphNames={},done={},active={};
            for(g=0;g<graph.symbols.length;g++)graphNames['$'+graph.symbols[g].name]=graph.symbols[g];
            function visit(name,stack){
                if(active['$'+name]){graph.cycles.push(stack.concat([name]));need(graph.cycles.length<=128,'Too many dependency cycles');return;}
                if(done['$'+name]||!graphNames['$'+name])return;
                active['$'+name]=true;var dependencies=graphNames['$'+name].dependencies;
                for(var v=0;v<dependencies.length;v++)visit(dependencies[v],stack.concat([name]));
                active['$'+name]=false;done['$'+name]=true;
            }
            for(g=0;g<graph.symbols.length;g++)visit(graph.symbols[g].name,[]);
            return encode({ok:true,data:graph});
        }
        target=targetTimeline(scope.symbol_name);targetFrame=target.currentFrame;targetLayer=target.currentLayer;
        var captured=capture(scope,target);
        if(packet.action==='inspectAnimation')return encode({ok:true,data:captured});
        need(captured.state_json===opts.expected_state,'Stale animation revision; inspect again before editing');
        alive();
        if(packet.action==='prepareBackup'){
            var snapshot=opts.output_uri+'snapshot.fla';need(!FLfile.exists(snapshot),'Snapshot destination exists');
            need(doc.saveAsCopy(snapshot,false)===true,'Could not prepare snapshot; no edits applied');
            return encode({ok:true,data:{snapshot_prepared:true}});
        }
        if(packet.action==='authorScene'){
            need(opts.frame_count>=target.frameCount,'Authoring cannot shorten the timeline');
            need(target.layers.length+opts.instances.length<=200,'Too many layers');
            for(var s=0;s<opts.symbols.length;s++)need(!libraryItem(opts.symbols[s].name),'Existing symbol cannot be replaced');
            for(var p=0;p<opts.instances.length;p++){
                var placement=opts.instances[p];
                for(var n=0;n<target.layers.length;n++)need(target.layers[n].name!==placement.layer,'Existing layer cannot be replaced');
                need(placement.symbol!==scope.symbol_name,'Recursive symbol placement is forbidden');
                var found=libraryItem(placement.symbol);for(s=0;s<opts.symbols.length;s++)if(opts.symbols[s].name===placement.symbol)found={itemType:'graphic',frameCount:opts.symbols[s].frames.length};
                need(found&&found.itemType==='graphic','Placement requires a graphic symbol');
                if(scope.symbol_name!==null&&found.timeline)need(!references(found,scope.symbol_name,{},{count:0}),'Placement would create a symbol dependency cycle');
                need((placement.firstFrame||0)<(found.timeline?found.timeline.frameCount:found.frameCount),'Graphic pose exceeds symbol frames');
            }
            backedUp();oldFill=doc.getCustomFill('toolbar');oldStroke=doc.getCustomStroke('toolbar');
            for(s=0;s<opts.symbols.length;s++){
                alive();var art=opts.symbols[s];need(doc.library.addNewItem('graphic',art.name),'Could not create graphic');
                need(doc.library.editItem(art.name),'Could not edit new graphic');entered=true;
                var artTimeline=doc.getTimeline();if(art.frames.length>1)artTimeline.insertFrames(art.frames.length-1,false,0);
                for(f=0;f<art.frames.length;f++){
                    if(f>0&&artTimeline.layers[0].frames[f].startFrame!==f)artTimeline.insertBlankKeyframe(f);
                    artTimeline.currentLayer=0;artTimeline.currentFrame=f;
                    for(g=0;g<art.frames[f].length;g++)draw(art.frames[f][g]);
                }
                artTimeline.currentFrame=0;doc.exitEditMode();entered=false;applied++;
            }
            if(scope.symbol_name!==null){need(doc.library.editItem(scope.symbol_name),'Could not enter target symbol');entered=true;}
            target=doc.getTimeline();target.currentFrame=0;
            if(opts.frame_count>target.frameCount)target.insertFrames(opts.frame_count-target.frameCount,true,target.frameCount-1);
            for(p=0;p<opts.instances.length;p++){
                alive();placement=opts.instances[p];var newLayer=target.addNewLayer(placement.layer,'normal',true);target.currentLayer=newLayer;target.currentFrame=0;
                if(target.layers[newLayer].frames.length<opts.frame_count)target.insertFrames(opts.frame_count-target.layers[newLayer].frames.length,false,0);
                doc.selectNone();need(doc.library.addItemToDocument({x:placement.x,y:placement.y},placement.symbol),'Could not place graphic');
                need(doc.selection.length===1,'Expected one placed instance');var instance=doc.selection[0];
                instance.name=placement.name;var angle=(placement.rotation||0)*Math.PI/180,sx=placement.scaleX===undefined?1:placement.scaleX,sy=placement.scaleY===undefined?1:placement.scaleY;
                var pivot=placement.pivot||{x:0,y:0},a=Math.cos(angle)*sx,b=Math.sin(angle)*sx,c=-Math.sin(angle)*sy,d=Math.cos(angle)*sy;
                var placedMatrix={a:a,b:b,c:c,d:d,tx:placement.x-a*pivot.x-c*pivot.y,ty:placement.y-b*pivot.x-d*pivot.y};instance.matrix=placedMatrix;
                instance.loop=placement.playback||'single frame';instance.firstFrame=placement.firstFrame||0;
                instance.colorMode='alpha';instance.colorAlphaPercent=placement.alpha===undefined?100:placement.alpha;
                if(placement.pivot)instance.setTransformationPoint(placement.pivot);verifyMatrix(instance.matrix,placedMatrix);
                need(instance.firstFrame===(placement.firstFrame||0)&&instance.loop===(placement.playback||'single frame'),'Graphic placement readback differs');
                doc.selectNone();applied++;
            }
            need(target.frameCount===opts.frame_count,'Unexpected authoring timeline length');
            return encode({ok:true,data:{created_symbols:opts.symbols.length,created_instances:opts.instances.length,frame_count:target.frameCount,symbol_name:scope.symbol_name,applied:applied}});
        }
        if(packet.action==='applyPoses'){
            for(p=0;p<opts.poses.length;p++){
                var pose=opts.poses[p];need(pose.frame>=scope.start_frame&&pose.frame<=scope.end_frame&&contains(scope.layers,pose.layer),'Pose outside inspected scope');
                instance=named(target,pose.layer,pose.instance,pose.frame);need(pose.firstFrame<instance.libraryItem.timeline.frameCount,'Graphic pose exceeds symbol timeline');
            }
            backedUp();
            if(scope.symbol_name!==null){need(doc.library.editItem(scope.symbol_name),'Could not enter inspected symbol');entered=true;target=doc.getTimeline();}
            for(p=0;p<opts.poses.length;p++){
                alive();pose=opts.poses[p];target.currentLayer=layerIndex(target,pose.layer);target.currentFrame=pose.frame;
                if(target.layers[target.currentLayer].frames[pose.frame].startFrame!==pose.frame)target.insertKeyframe(pose.frame);
                instance=named(target,pose.layer,pose.instance,pose.frame);instance.matrix=pose.matrix;
                instance.colorMode='alpha';instance.colorAlphaPercent=pose.alpha;instance.loop=pose.loop||'single frame';instance.firstFrame=pose.firstFrame;
                target.layers[target.currentLayer].frames[pose.frame].tweenType='none';applied++;
            }
            var maximumError=0;
            for(p=0;p<opts.poses.length;p++){
                pose=opts.poses[p];instance=named(target,pose.layer,pose.instance,pose.frame);
                maximumError=Math.max(maximumError,verifyMatrix(instance.matrix,pose.matrix));
                need(instance.firstFrame===pose.firstFrame&&instance.loop===(pose.loop||'single frame')&&Math.abs(instance.colorAlphaPercent-pose.alpha)<=.051,'Graphic pose/playback/alpha readback differs');
            }
            return encode({ok:true,data:{applied:applied,readback_verified:true,max_matrix_error:maximumError,symbol_name:scope.symbol_name}});
        }
        need(scope.symbol_name===null,'Project/audio operations require root scope');
        if(packet.action==='saveProject'){
            backedUp();need(fl.saveDocument(doc,opts.managed_project_uri)===true,'Could not save managed project');return encode({ok:true,data:{saved:true,document_id:doc.id}});
        }
        if(packet.action==='setAudio'){
            for(n=0;n<root.layers.length;n++)need(root.layers[n].name!==opts.layer,'Existing audio layer cannot be replaced');
            need(opts.start_frame<root.frameCount,'Audio begins outside scene');backedUp();
            var before=[];for(n=0;n<doc.library.items.length;n++)before.push(doc.library.items[n].name);
            doc.importFile(opts.audio_uri,true);var sound=null;
            for(n=0;n<doc.library.items.length;n++)if(doc.library.items[n].itemType==='sound'&&!contains(before,doc.library.items[n].name)){need(sound===null,'Ambiguous sound import');sound=doc.library.items[n];}
            need(sound,'PCM sound import failed');newLayer=root.addNewLayer(opts.layer,'normal',true);root.currentLayer=newLayer;
            if(root.layers[newLayer].frames.length<root.frameCount)root.insertFrames(root.frameCount-root.layers[newLayer].frames.length,false,0);
            if(opts.start_frame>0)root.insertBlankKeyframe(opts.start_frame);
            var soundFrame=root.layers[newLayer].frames[opts.start_frame];soundFrame.soundLibraryItem=sound;soundFrame.soundSync='stream';soundFrame.soundLoop=1;
            return encode({ok:true,data:{layer:opts.layer,start_frame:opts.start_frame,sound_name:short(sound.name),sync:'stream',frame_rate:doc.frameRate}});
        }
        throw new Error('Unsupported animation action');
    }catch(error){return encode({ok:false,error:String(error).slice(0,800)+(backup?'; backup exists; applied '+applied+' operation(s); inspect before retrying':'')});}
    finally{
        if(entered&&doc){try{doc.exitEditMode();}catch(_){}}
        if(root&&oldFrame!==null){try{root.currentFrame=Math.min(oldFrame,root.frameCount-1);root.currentLayer=Math.min(oldLayer,root.layers.length-1);}catch(_){}}
        if(target&&target!==root&&targetFrame!==null){try{target.currentFrame=targetFrame;target.currentLayer=targetLayer;}catch(_){}}
        if(doc){try{doc.selectNone();if(oldFill)doc.setCustomFill(oldFill);if(oldStroke)doc.setCustomStroke(oldStroke);if(oldSelection)doc.selection=oldSelection;}catch(_){}}
        if(oldDoc)fl.setActiveWindow(oldDoc);
    }
}
