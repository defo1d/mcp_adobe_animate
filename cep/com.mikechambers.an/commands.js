/* Animate host operations. Only fixed code + serialized data reach JSFL by default. */
'use strict';

function runInHost(packet, rawFunction) {
    // This function is serialized into JSFL; keep its syntax compatible with ES5.
    function quote(s) {
        return '"' + String(s).replace(/[\\"\x00-\x1f\x7f-\uffff]/g, function (c) {
            var code = c.charCodeAt(0).toString(16);
            return '\\u' + ('0000' + code).slice(-4);
        }) + '"';
    }
    function encode(v) {
        if (v === null || v === undefined) return 'null';
        if (typeof v === 'string') return quote(v);
        if (typeof v === 'number') return isFinite(v) ? String(v) : 'null';
        if (typeof v === 'boolean') return String(v);
        var a = [], i, k;
        if (v instanceof Array) {
            for (i = 0; i < v.length; i++) a.push(encode(v[i]));
            return '[' + a.join(',') + ']';
        }
        for (k in v) if (Object.prototype.hasOwnProperty.call(v, k)) a.push(quote(k) + ':' + encode(v[k]));
        return '{' + a.join(',') + '}';
    }
    function requireValue(ok, message) { if (!ok) throw new Error(message); }
    function shortText(s) { return String(s || '').slice(0, 256); }
    var opts = packet.options;
    var doc = null, tl = null, oldDoc = null, oldFrame = null, oldLayer = null;
    try {
        var docs = fl.documents;
        var i, j, data, item;
        if (packet.action === 'createProject' || packet.action === 'openProject') {
            requireValue(docs.length < 32, 'Too many open documents');
            requireValue((new Date()).getTime() < packet.expires_at, 'Project request expired');
            if (packet.action === 'createProject') {
                var destination = opts.output_uri + 'project.fla';
                requireValue(!FLfile.exists(destination), 'Project destination already exists');
                var fresh = fl.createDocument();
                requireValue(!!fresh, 'Could not create a new document');
                fresh.width = opts.width; fresh.height = opts.height;
                fresh.frameRate = opts.frame_rate; fresh.backgroundColor = opts.background;
                if (opts.template === 'smoke_test') {
                    function oval(l,t,r,b,color) {
                        fresh.selectNone();
                        var fill = fresh.getCustomFill('toolbar'); fill.style = 'solid'; fill.color = color;
                        fresh.setCustomFill(fill); fresh.addNewOval({left:l,top:t,right:r,bottom:b},false,true);
                    }
                    oval(80,130,160,230,'#191D28'); oval(85,135,155,225,'#31B99A');
                    oval(96,155,116,181,'#FFFFFF'); oval(124,155,144,181,'#FFFFFF');
                    oval(104,163,112,177,'#191D28'); oval(132,163,140,177,'#191D28');
                    oval(108,190,139,208,'#191D28'); fresh.selectAll();
                    requireValue(fresh.convertToSymbol('graphic','MCP_Test_Actor','center'), 'Could not create test symbol');
                    fresh.selection[0].name = 'mcp_actor'; fresh.selection[0].loop = 'single frame';
                    var freshTimeline = fresh.getTimeline(); freshTimeline.layers[0].name = 'MCP test actor';
                    freshTimeline.insertFrames(47,true,0); freshTimeline.insertKeyframe(47); freshTimeline.currentFrame = 0;
                    fresh.selectNone();
                }
                requireValue(fl.saveDocument(fresh,destination) === true && FLfile.exists(destination), 'Could not save the new project');
                item = fresh;
            } else {
                requireValue(FLfile.exists(opts.project_uri), 'Managed project is missing');
                item = null;
                for (i=0; i<docs.length; i++) if (docs[i].pathURI === opts.project_uri) {item=docs[i];break;}
                if (item) fl.setActiveWindow(item);
                else item = fl.openDocument(opts.project_uri);
                requireValue(!!item, 'Could not open the managed project');
            }
            return encode({ok:true,data:{document_id:item.id,name:shortText(item.name),
                width:item.width,height:item.height,frame_rate:item.frameRate,timeline_index:item.currentTimeline,
                frame_count:item.getTimeline().frameCount}});
        }
        if (packet.action === 'getDocuments') {
            data = [];
            requireValue(docs.length <= 32, 'Too many open documents');
            for (i = 0; i < docs.length; i++) {
                item = docs[i];
                data.push({document_id: item.id, name: shortText(item.name), path: shortText(item.path || 'Unsaved'),
                           width: item.width, height: item.height, frame_rate: item.frameRate, timeline_index: item.currentTimeline});
            }
            return encode({ok: true, data: data});
        }
        for (i = 0; i < docs.length; i++) if (docs[i].id === opts.document_id) { doc = docs[i]; break; }
        requireValue(doc !== null, 'Pinned document is closed or unavailable');
        oldDoc = fl.getDocumentDOM();
        fl.setActiveWindow(doc);
        requireValue(fl.getDocumentDOM().id === opts.document_id, 'Document focus changed');
        tl = doc.getTimeline();
        oldFrame = tl.currentFrame; oldLayer = tl.currentLayer;
        if (packet.action === 'exportFrames' || packet.action === 'applyAnimation') {
            requireValue(doc.currentTimeline === opts.timeline_index, 'Scene changed; inspect timeline before retrying');
            requireValue(!tl.libraryItem, 'Exit symbol editing before exporting or editing scene animation');
        }
        requireValue(tl.frameCount <= 10000 && tl.layers.length <= 200, 'Timeline exceeds configured bounds');
        if (packet.action === 'getTimeline') {
            data = {document_id: doc.id, timeline_index: doc.currentTimeline, name: shortText(tl.name),
                    frame_count: tl.frameCount, current_frame: tl.currentFrame, layers: []};
            var budget = 1024, used = encode(data).length, truncated = false;
            for (i = 0; i < tl.layers.length && budget > 0; i++) {
                var layer = tl.layers[i], frames = [];
                var layerData = {index: i, name: shortText(layer.name), type: shortText(layer.layerType),
                                 locked: layer.locked, visible: layer.visible, keyframes: frames};
                var headerSize = encode(layerData).length + 1;
                if (used + headerSize > 40000) { truncated = true; break; }
                used += headerSize;
                for (j = 0; j < layer.frames.length && budget > 0; j++) {
                    var frame = layer.frames[j];
                    if (frame.startFrame !== j) continue;
                    var names = [];
                    for (var e = 0; e < Math.min(frame.elements.length, 32); e++) {
                        var el = frame.elements[e];
                        names.push({name: shortText(el.name), type: shortText(el.elementType), x: el.x, y: el.y});
                    }
                    var record = {frame: j, duration: frame.duration, tween: shortText(frame.tweenType),
                                  elements: names, truncated_elements: frame.elements.length > names.length};
                    var recordSize = encode(record).length + 1;
                    while (used + recordSize > 40000 && names.length > 0) {
                        names.pop(); record.truncated_elements = true;
                        recordSize = encode(record).length + 1;
                    }
                    if (used + recordSize > 40000) { truncated = true; break; }
                    frames.push(record); used += recordSize;
                    truncated = truncated || record.truncated_elements;
                    budget--;
                }
                data.layers.push(layerData);
                if (j < layer.frames.length) truncated = true;
            }
            data.total_layers = tl.layers.length;
            data.truncated = truncated || budget === 0 || i < tl.layers.length;
        } else if (packet.action === 'getLibrary') {
            data = {document_id: doc.id, items: [], total_items: doc.library.items.length, truncated: false};
            requireValue(doc.library.items.length <= 1024, 'Library exceeds bounds');
            var librarySize = encode(data).length;
            for (i = 0; i < doc.library.items.length; i++) {
                item = doc.library.items[i];
                var entry = {name: shortText(item.name), type: shortText(item.itemType)};
                var entrySize = encode(entry).length + 1;
                if (librarySize + entrySize > 40000) { data.truncated = true; break; }
                data.items.push(entry); librarySize += entrySize;
            }
        } else if (packet.action === 'exportFrames') {
            requireValue(!tl.libraryItem, 'Exit symbol editing before exporting stage frames');
            requireValue(opts.end_frame < tl.frameCount, 'Frame range exceeds timeline');
            requireValue(doc.width > 0 && doc.width <= 4096 && doc.height > 0 && doc.height <= 4096, 'Stage exceeds export bounds');
            var ordinal = 0, totalBytes = 0;
            for (i = opts.start_frame; i <= opts.end_frame; i += opts.step) {
                requireValue((new Date()).getTime() < packet.expires_at, 'Export request expired');
                tl.currentFrame = i; ordinal++;
                var uri = opts.output_uri + 'frame-' + ('000000' + ordinal).slice(-6) + '.png';
                requireValue(!FLfile.exists(uri), 'Export would overwrite an existing file');
                requireValue(doc.exportPNG(uri, true, true) === true, 'PNG export failed at frame ' + i);
                var bytes = Number(FLfile.getSize(uri));
                requireValue(isFinite(bytes) && bytes > 0 && bytes <= 8388608, 'PNG exceeds 8 MiB');
                totalBytes += bytes;
                requireValue(totalBytes <= 268435456, 'Export exceeds 256 MiB');
            }
            data = {document_id: doc.id, document_name: shortText(doc.name), frame_rate: doc.frameRate, count: ordinal};
        } else if (packet.action === 'exportSpriteSheet' || packet.action === 'exportAllSpriteSheets') {
            var items = [];
            for (i = 0; i < doc.library.items.length; i++) {
                item = doc.library.items[i];
                if (packet.action === 'exportSpriteSheet') {
                    if (item.name === opts.symbol_name) items.push(item);
                } else if (item.itemType === 'movie clip' || item.itemType === 'graphic') items.push(item);
            }
            requireValue(items.length > 0 && items.length <= 64, 'No matching symbol or more than 64 symbols');
            var spriteBytes = 0;
            for (i = 0; i < items.length; i++) {
                requireValue((new Date()).getTime() < packet.expires_at, 'Export request expired');
                var exporter = new SpriteSheetExporter();
                exporter.addSymbol(items[i]); exporter.layoutFormat = 'JSON';
                exporter.maxSheetWidth = opts.max_width === undefined ? 2048 : opts.max_width;
                exporter.maxSheetHeight = opts.max_height === undefined ? 2048 : opts.max_height;
                exporter.borderPadding = opts.padding === undefined ? 2 : opts.padding;
                exporter.shapePadding = exporter.borderPadding;
                exporter.autoSize = true; exporter.allowTrimming = true;
                var base = opts.output_uri + 'sprite-' + ('000000' + (i + 1)).slice(-6);
                requireValue(!FLfile.exists(base + '.png') && !FLfile.exists(base + '.json'), 'Export would overwrite an existing file');
                exporter.exportSpriteSheet(base, {format: 'png', bitDepth: 32, backgroundColor: '#00000000'}, true);
                requireValue(!exporter.overflowed, 'Symbol frames do not fit within sprite sheet bounds');
                requireValue(FLfile.exists(base + '.png'), 'Sprite export failed');
                var sheetBytes = Number(FLfile.getSize(base + '.png'));
                requireValue(isFinite(sheetBytes) && sheetBytes > 0 && sheetBytes <= 8388608, 'Sprite PNG exceeds 8 MiB');
                var jsonBytes = Number(FLfile.getSize(base + '.json'));
                requireValue(isFinite(jsonBytes) && jsonBytes > 0 && jsonBytes <= 8388608, 'Sprite metadata missing or exceeds 8 MiB');
                spriteBytes += sheetBytes + jsonBytes;
                requireValue(spriteBytes <= 268435456, 'Sprite export exceeds 256 MiB');
            }
            data = {count: items.length};
        } else if (packet.action === 'applyAnimation') {
            function namedInstance(op) {
                var frame = tl.layers[op.layer].frames[op.frame];
                var found = null;
                for (var n = 0; n < frame.elements.length; n++) {
                    var el = frame.elements[n];
                    if (el.name === op.instance && el.elementType === 'instance') {
                        requireValue(found === null, 'Duplicate instance name'); found = el;
                    }
                }
                requireValue(found !== null, 'Named symbol instance not found: ' + op.instance);
                requireValue(found.instanceType === 'symbol', 'Pose target must be a symbol');
                if (op.values.firstFrame !== undefined || op.values.loop !== undefined)
                    requireValue(found.symbolType === 'graphic', 'Mouth/playback settings require a graphic symbol');
                if (op.values.firstFrame !== undefined)
                    requireValue(op.values.firstFrame < found.libraryItem.timeline.frameCount, 'Graphic frame outside symbol timeline');
                return found;
            }
            // Check every target before creating a backup or changing the document.
            for (i = 0; i < opts.operations.length; i++) {
                var op = opts.operations[i];
                requireValue(op.layer < tl.layers.length && !tl.layers[op.layer].locked, 'Missing or locked layer');
                if (op.type === 'pose') {
                    requireValue(op.frame < tl.layers[op.layer].frames.length, 'Pose frame outside layer'); namedInstance(op);
                } else {
                    requireValue(op.end_frame < tl.layers[op.layer].frames.length, 'Tween frame outside layer');
                    requireValue(tl.layers[op.layer].frames[op.start_frame].startFrame === op.start_frame &&
                                 tl.layers[op.layer].frames[op.end_frame].startFrame === op.end_frame, 'Tween endpoints must already be keyframes');
                    for (var between = op.start_frame + 1; between < op.end_frame; between++)
                        requireValue(tl.layers[op.layer].frames[between].startFrame !== between,
                                     'Tween endpoints must be adjacent keyframes');
                    for (var planned = 0; planned < opts.operations.length; planned++) {
                        var pose = opts.operations[planned];
                        requireValue(!(pose.type === 'pose' && pose.layer === op.layer &&
                                       pose.frame > op.start_frame && pose.frame < op.end_frame),
                                     'A planned pose would split the requested tween');
                    }
                }
            }
            var backup = opts.output_uri + 'backup.fla';
            requireValue(!FLfile.exists(backup), 'Backup destination already exists');
            requireValue(doc.saveAsCopy(backup, false) === true && FLfile.exists(backup), 'Backup failed; no edits applied');
            requireValue(Number(FLfile.getSize(backup)) > 0, 'Backup is empty; no edits applied');
            for (i = 0; i < opts.operations.length; i++) {
                requireValue((new Date()).getTime() < packet.expires_at, 'Edit request expired; restore backup if needed');
                op = opts.operations[i]; tl.currentLayer = op.layer;
                if (op.type === 'pose') {
                    tl.currentFrame = op.frame;
                    // Animate can duplicate/extend the timeline when reinserting an existing key.
                    if (tl.layers[op.layer].frames[op.frame].startFrame !== op.frame) tl.insertKeyframe(op.frame);
                    var target = namedInstance(op);
                    for (var key in op.values) if (Object.prototype.hasOwnProperty.call(op.values, key)) {
                        if (key === 'alpha') { target.colorMode = 'alpha'; target.colorAlphaPercent = op.values[key]; }
                        else target[key] = op.values[key];
                    }
                } else {
                    tl.layers[op.layer].frames[op.start_frame].tweenType = 'motion';
                    tl.layers[op.layer].frames[op.start_frame].tweenEasing = op.easing;
                }
            }
            data = {applied: opts.operations.length, document_id: doc.id};
        } else if (packet.action === 'executeExtendScript' && typeof rawFunction === 'function') {
            data = {value: rawFunction(doc)};
        } else throw new Error('Unsupported host action');
        return encode({ok: true, data: data});
    } catch (error) {
        return encode({ok: false, error: String(error).slice(0, 1024)});
    } finally {
        if (tl && oldFrame !== null) { tl.currentFrame = oldFrame; tl.currentLayer = oldLayer; }
        if (oldDoc) fl.setActiveWindow(oldDoc);
    }
}

function executePacket(packet, session, allowScripts, approve) {
    const actions = ['createProject', 'openProject', 'getDocuments', 'getTimeline', 'getLibrary', 'exportFrames', 'exportSpriteSheet',
        'exportAllSpriteSheets', 'applyAnimation', 'executeExtendScript'];
    if (!packet || actions.indexOf(packet.action) < 0 || packet.session !== session ||
        !/^[0-9a-f]{32}$/.test(packet.id) || !Number.isFinite(packet.expires_at) || Date.now() >= packet.expires_at)
        return Promise.resolve({ok: false, error: 'Rejected or expired packet'});
    const raw = packet.action === 'executeExtendScript';
    if (raw && (!allowScripts || !approve(packet)))
        return Promise.resolve({ok: false, error: 'Arbitrary JSFL was not approved'});
    // Recheck expiration after a potentially long modal approval.
    if (Date.now() >= packet.expires_at)
        return Promise.resolve({ok: false, error: 'Approval expired'});
    const data = JSON.stringify(packet).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
    let script = '(' + runInHost.toString() + ')(' + data;
    if (raw) script += ', function(doc) {\n' + packet.options.script + '\n}';
    script += ')';
    return new Promise(function (resolve) {
        new CSInterface().evalScript(script, function (result) {
            try {
                if (result === 'EvalScript error.' || typeof result !== 'string' || result.length > 131072)
                    throw new Error('Host execution failed or response exceeded bounds');
                const value = JSON.parse(result);
                if (!value || typeof value.ok !== 'boolean') throw new Error('Invalid host response');
                resolve(value);
            } catch (error) { resolve({ok: false, error: error.message}); }
        });
    });
}
