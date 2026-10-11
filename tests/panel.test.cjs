'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const commands = fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/commands.js'), 'utf8');

function harness() {
    const files = new Map();
    const state = {calls: 0, exports: [], backups: [], edits: [], active: null, failExport: false, failBackup: false, backupBytes: 50};
    const element = () => ({name: 'mouth', elementType: 'instance', instanceType: 'symbol', symbolType: 'graphic', libraryItem: {timeline: {frameCount: 5}}, x: 0, y: 0});
    const frame0 = {startFrame: 0, duration: 2, elements: [element()], tweenType: 'none'};
    const frame2 = {startFrame: 2, duration: 1, elements: [element()], tweenType: 'none'};
    const layer = {name: 'character', layerType: 'normal', locked: false, visible: true, frames: [frame0, frame0, frame2]};
    const tl = {name: 'Scene 1', frameCount: 3, currentFrame: 1, currentLayer: 0, layers: [layer],
        insertKeyframe(n) { state.edits.push(n); if (layer.frames[n].startFrame !== n) layer.frames[n] = {startFrame: n, duration: 1, elements: [element()], tweenType: 'none'}; }};
    const doc = {id: 11, name: 'scene.fla', path: '', width: 1280, height: 720, frameRate: 24, currentTimeline: 0, library: {items: [{name: 'mouth', itemType: 'graphic'}]}, getTimeline: () => tl,
        exportPNG(uri, settings, current) { state.exports.push({uri, frame: tl.currentFrame, settings, current}); if (state.failExport) return false; files.set(uri, 100); return true; },
        saveAsCopy(uri) {state.backups.push(uri); if (state.failBackup) return false; files.set(uri, state.backupBytes); return true;}};
    const other = {id: 12, name: 'other.fla', path: '', width: 1, height: 1, frameRate: 24, currentTimeline: 0};
    state.active = other;
    const host = vm.createContext({fl: {documents: [doc, other], getDocumentDOM: () => state.active, setActiveWindow: d => {state.active = d;}},
        FLfile: {exists: uri => files.has(uri), getSize: uri => files.has(uri) ? files.get(uri) : -1},
        SpriteSheetExporter: function () {this.addSymbol = item => { this.item = item; }; this.exportSpriteSheet = base => {state.spritePadding = this.borderPadding; state.spriteItem = this.item; files.set(base + '.png', 100); files.set(base + '.json', 100);};}});
    const panel = vm.createContext({console});
    panel.window = panel;
    panel.__adobe_cep__ = {evalScript(source, callback) {state.calls++; state.source = source; try {callback(vm.runInContext(source, host));} catch (e) {callback('EvalScript error.');}}};
    vm.runInContext(fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/host.js'), 'utf8'), panel);
    vm.runInContext(commands, panel);
    const packet = (action, options = {}) => ({id: 'a'.repeat(32), session: 'b'.repeat(32), expires_at: Date.now() + 10000, action, options: {document_id: 11, timeline_index: 0, ...options}});
    const run = (p, allow = false, approve = () => false) => panel.executePacket(p, 'b'.repeat(32), allow, approve);
    return {run, packet, state, doc, other, tl, layer, files, host, panel};
}

test('unsafe aliases, wrong sessions, expired packets and raw JSFL never reach host', async () => {
    const h = harness();
    for (const p of [h.packet('constructor'), h.packet('__proto__'), {...h.packet('getLibrary'), session: 'c'.repeat(32)}, {...h.packet('getLibrary'), expires_at: 1}, h.packet('executeExtendScript', {script: 'fl.injected = true;'})]) {
        assert.equal((await h.run(p)).ok, false);
    }
    assert.equal(h.state.calls, 0);
});
test('raw JSFL needs both local opt-in and exact manual approval and expires after modal', async () => {
    const h = harness(); const p = h.packet('executeExtendScript', {script: 'return doc.id;'});
    assert.equal((await h.run(p, true)).ok, false);
    const approved = await h.run(p, true, q => q === p);
    assert.equal(approved.ok, true); assert.equal(approved.data.value, 11);
    const q = h.packet('executeExtendScript', {script: 'fl.injected = true;'});
    assert.equal((await h.run(q, true, current => {current.expires_at = 1; return true;})).ok, false);
    assert.equal(h.host.fl.injected, undefined); assert.equal(h.state.calls, 1);
});
test('document identity pinned and prior document, frame, layer restored', async () => {
    const h = harness(); const r = await h.run(h.packet('getTimeline'));
    assert.equal(r.ok, true); assert.equal(r.data.document_id, 11); assert.equal(r.data.layers[0].keyframes.length, 2);
    assert.equal(h.state.active, h.other); assert.equal(h.tl.currentFrame, 1);
    const missing = await h.run(h.packet('getLibrary', {document_id: 999}));
    assert.equal(missing.ok, false); assert.equal(h.state.active, h.other);
});
test('creating a project changes only a fresh document and refuses overwrites before creation', async () => {
    const h=harness(); let created=0;
    const fresh={id:13,name:'project.fla',currentTimeline:0,getTimeline:()=>({frameCount:1})};
    h.host.fl.createDocument=()=>{created++;h.state.active=fresh;return fresh;};
    h.host.fl.saveDocument=(doc,uri)=>{assert.equal(doc,fresh);h.files.set(uri,100);return true;};
    const opts={width:640,height:360,frame_rate:24,background:'#F4F0E7',template:'blank',output_uri:'file:///private/new/'};
    const result=await h.run(h.packet('createProject',opts));
    assert.equal(result.ok,true);assert.equal(result.data.document_id,13);assert.equal(h.state.active,fresh);
    assert.equal(h.doc.width,1280);assert.equal(h.state.edits.length,0);assert.equal(h.state.backups.length,0);
    assert.equal((await h.run(h.packet('createProject',opts))).ok,false);assert.equal(created,1);
});
test('opening an already-open managed project focuses it without reopening or modifying it', async () => {
    const h=harness();h.doc.pathURI='file:///private/managed/project.fla';h.files.set(h.doc.pathURI,100);
    h.host.fl.openDocument=()=>{throw new Error('Should reuse existing open document');};
    const result=await h.run(h.packet('openProject',{run_id:'run-'+'c'.repeat(32),project_uri:h.doc.pathURI}));
    assert.equal(result.ok,true);assert.equal(result.data.document_id,11);assert.equal(h.state.active,h.doc);
    assert.equal(h.state.edits.length,0);assert.equal(h.state.backups.length,0);
});
test('symbol names serialized literally instead of JSFL injection, zero padding retained', async () => {
    const h = harness(); const name = '\"); fl.injected = true; //\u2028\u2029';
    h.doc.library.items = [{name, itemType: 'graphic'}];
    const r = await h.run(h.packet('exportSpriteSheet', {symbol_name: name, output_uri: 'file:///private/export%20space/', max_width: 512, max_height: 512, padding: 0}));
    assert.equal(r.ok, true); assert.equal(h.state.spriteItem.name, name); assert.equal(h.state.spritePadding, 0);
    assert.equal(h.host.fl.injected, undefined); assert.ok(!h.state.source.includes('\u2028'));
    assert.ok(h.files.has('file:///private/export%20space/sprite-000001.png'));
});
test('PNG export selects requested frames and passes current-frame flags', async () => {
    const h = harness(); const r = await h.run(h.packet('exportFrames', {start_frame: 0, end_frame: 2, step: 2, output_uri: 'file:///private/export/'}));
    assert.equal(r.ok, true); assert.equal(r.data.count, 2);
    assert.deepEqual(h.state.exports.map(x => x.frame), [0, 2]);
    assert.ok(h.state.exports.every(x => x.settings === true && x.current === true));
    assert.equal(h.tl.currentFrame, 1); assert.equal(h.state.active, h.other);
});
test('failed PNG export and symbol editing fail closed and restore focus/frame', async () => {
    const h = harness(); h.state.failExport = true;
    const p = h.packet('exportFrames', {start_frame: 0, end_frame: 2, step: 1, output_uri: 'file:///private/export/'});
    assert.equal((await h.run(p)).ok, false); assert.equal(h.tl.currentFrame, 1); assert.equal(h.state.active, h.other);
    h.tl.libraryItem = {};
    assert.equal((await h.run(p)).ok, false); assert.equal(h.state.exports.length, 1);
});
test('empty or failed backup prevents every mutation', async () => {
    for (const setting of [{failBackup: true}, {backupBytes: 0}]) {
        const h = harness(); Object.assign(h.state, setting);
        const r = await h.run(h.packet('applyAnimation', {output_uri: 'file:///private/export/', operations: [{type: 'pose', layer: 0, frame: 1, instance: 'mouth', values: {x: 100}}]}));
        assert.equal(r.ok, false); assert.equal(h.state.edits.length, 0); assert.equal(h.tl.currentFrame, 1); assert.equal(h.state.active, h.other);
    }
});
test('poses, graphic mouth frames and classic tween applied after backup', async () => {
    const h = harness(); const r = await h.run(h.packet('applyAnimation', {output_uri: 'file:///private/export/', operations: [
        {type: 'pose', layer: 0, frame: 2, instance: 'mouth', values: {x: 100, firstFrame: 3, loop: 'single frame', alpha: 80}},
        {type: 'classic_tween', layer: 0, start_frame: 0, end_frame: 2, easing: -50}]}));
    assert.equal(r.ok, true); assert.equal(r.data.applied, 2); assert.equal(h.state.backups.length, 1);
    assert.equal(h.layer.frames[2].elements[0].x, 100); assert.equal(h.layer.frames[2].elements[0].firstFrame, 3);
    assert.equal(h.layer.frames[2].elements[0].colorAlphaPercent, 80); assert.equal(h.layer.frames[0].tweenType, 'motion');
    assert.equal(h.state.edits.length,0); // The endpoints were already keyframes; never reinsert them.
    assert.equal(h.layer.frames[0].tweenEasing, -50); assert.equal(h.state.active, h.other); assert.equal(h.tl.currentFrame, 1);
});
test('preflight rejects locked/missing/duplicate targets and out-of-range mouth frames', async () => {
    for (const setup of [h => {h.layer.locked = true;}, h => {h.layer.frames[0].elements[0].name = 'other';}, h => {h.layer.frames[0].elements.push({...h.layer.frames[0].elements[0]});}, h => {h.layer.frames[0].elements[0].libraryItem.timeline.frameCount = 1;}]) {
        const h = harness(); setup(h);
        const r = await h.run(h.packet('applyAnimation', {output_uri: 'file:///private/export/', operations: [{type: 'pose', layer: 0, frame: 1, instance: 'mouth', values: {firstFrame: 2}}]}));
        assert.equal(r.ok, false); assert.equal(h.state.backups.length, 0); assert.equal(h.state.edits.length, 0);
    }
});
test('HTML preview playback, seeking and speed use exported frame rate', () => {
    const elements = {};
    for (const id of ['manifest','frame','seek','play','previous','next','speed','position']) elements[id] = {textContent: '', value: 1};
    elements.manifest.textContent = JSON.stringify({frames: ['frame-000001.png','frame-000002.png','frame-000003.png'], frame_numbers: [0,2,4], fps: 12});
    let interval, delay;
    const context = vm.createContext({document: {getElementById: id => elements[id]}, setInterval: (f, ms) => {interval = f; delay = ms; return 1;}, clearInterval: () => {interval = null;}});
    vm.runInContext(fs.readFileSync(path.join(root, 'mcp/preview_assets/preview.js'), 'utf8'), context);
    assert.equal(elements.frame.src, 'frame-000001.png'); assert.equal(elements.seek.max, 2);
    elements.next.onclick(); assert.equal(elements.frame.src, 'frame-000002.png');
    elements.play.onclick(); assert.equal(delay, 1000 / 12); interval(); assert.equal(elements.frame.src, 'frame-000003.png');
    elements.speed.value = 2; elements.speed.onchange(); assert.equal(delay, 1000 / 24);
    elements.seek.value = 0; elements.seek.oninput(); assert.equal(elements.frame.src, 'frame-000001.png'); assert.equal(elements.play.textContent, 'Play');
});
test('distribution has no CDN, eval JSON parser, Node CEP mode or debug port', () => {
    const dir = path.join(root, 'cep/com.mikechambers.an');
    const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
    const manifest = fs.readFileSync(path.join(dir, 'CSXS/manifest.xml'), 'utf8');
    assert.equal(fs.existsSync(path.join(dir, '.debug')), false);
    assert.ok(!manifest.includes('--enable-nodejs')); assert.ok(!manifest.includes('--mixed-context'));
    assert.ok(!html.includes('https://')); assert.ok(html.includes("default-src 'none'"));
    assert.ok(!commands.includes('eval('));
});
test('scene changes and symbol editing cannot mutate an unexpected timeline', async () => {
    for (const setup of [h => {h.doc.currentTimeline = 1;}, h => {h.tl.libraryItem = {}; }]) {
        const h = harness(); setup(h);
        const p = h.packet('applyAnimation', {output_uri: 'file:///private/export/', operations: [{type: 'pose', layer: 0, frame: 1, instance: 'mouth', values: {x: 20}}]});
        assert.equal((await h.run(p)).ok, false); assert.equal(h.state.backups.length, 0);
    }
});
test('classic tween rejects intermediate keyframes and planned poses splitting the span', async () => {
    for (const existing of [true, false]) {
        const h = harness();
        const tween = {type: 'classic_tween', layer: 0, start_frame: 0, end_frame: 2, easing: 0};
        const operations = [tween];
        if (existing) h.layer.frames[1] = {...h.layer.frames[0], startFrame: 1};
        else operations.push({type: 'pose', layer: 0, frame: 1, instance: 'mouth', values: {x: 20}});
        const r = await h.run(h.packet('applyAnimation', {output_uri: 'file:///private/export/', operations}));
        assert.equal(r.ok, false); assert.equal(h.state.backups.length, 0);
        assert.equal(h.layer.frames[0].tweenType, 'none');
    }
});
test('large libraries and timeline labels return bounded results with explicit truncation', async () => {
    const h = harness();
    h.doc.library.items = Array.from({length: 500}, (_, i) => ({name: 'Ж'.repeat(251) + String(i), itemType: 'graphic'}));
    const library = await h.run(h.packet('getLibrary'));
    assert.equal(library.ok, true); assert.equal(library.data.truncated, true); assert.equal(library.data.total_items, 500);
    assert.ok(library.data.items.length > 0 && library.data.items.length < 500);
    h.tl.layers = Array.from({length: 200}, (_, i) => ({...h.layer, name: 'Ж'.repeat(256), frames: [h.layer.frames[0]]}));
    const timeline = await h.run(h.packet('getTimeline'));
    assert.equal(timeline.ok, true); assert.equal(timeline.data.truncated, true); assert.equal(timeline.data.total_layers, 200);
    assert.ok(timeline.data.layers.length > 0 && timeline.data.layers.length < 200);
});
test('WebCrypto request and response proofs match standard HMAC and reject altered replies', async () => {
    const crypto = require('node:crypto');
    const context = vm.createContext({window: {crypto: crypto.webcrypto}, TextEncoder});
    vm.runInContext(fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/auth.js'), 'utf8'), context);
    const auth = vm.runInContext('AnimateAuth', context);
    const key = 'a'.repeat(64), instance = 'b'.repeat(32), body = '{"label":"Привет"}';
    const req = await auth.request(key, '127.0.0.1:3099', '/v1/panel/register', body, instance);
    const prefix = ['animate-mcp-safe-request-v1','POST','127.0.0.1:3099','/v1/panel/register',instance,req.stamp,req.nonce,body].join('\n');
    const expected = crypto.createHmac('sha256', Buffer.from(key, 'hex')).update(prefix).digest('hex');
    assert.equal(req.authorization, 'HMAC ' + expected); assert.ok(!req.authorization.includes(key));
    const response = '{"ok":true}';
    const signature = crypto.createHmac('sha256', Buffer.from(key, 'hex')).update(['animate-mcp-safe-response-v1',req.nonce,'200',response].join('\n')).digest('hex');
    await auth.verify(key, req.nonce, 200, response, signature);
    await assert.rejects(auth.verify(key, req.nonce, 200, response + ' ', signature), /authentication failed/);
    await assert.rejects(auth.verify(key, 'c'.repeat(32), 200, response, signature), /authentication failed/);
});
test('fake local server cannot pair the panel or deliver commands; no bearer token sent', async () => {
    const crypto = require('node:crypto');
    const elements = {}, captured = [];
    for (const id of ['btnConnect','statusText','messageLog','pairToken','port','pairFile']) elements[id] = {value: '', textContent: '', addEventListener(event, fn) {this[event] = fn;}};
    elements.pairToken.value = 'a'.repeat(64); elements.port.value = '3099';
    const context = vm.createContext({setTimeout, clearTimeout, TextEncoder, window: {crypto: crypto.webcrypto, addEventListener() {}, confirm() {throw new Error('Unexpected approval');}}, document: {getElementById: id => elements[id]},
        XMLHttpRequest: function () {
            this.headers = {}; this.open = (method, url) => {this.url = url;};
            this.setRequestHeader = (name, value) => {this.headers[name] = value;};
            this.getResponseHeader = () => '0'.repeat(64);
            this.send = body => {captured.push({url: this.url, headers: this.headers, body}); this.status = 200; this.responseText = JSON.stringify({ok: true, data: {instance: 'b'.repeat(32)}}); this.onload();};
        }, executePacket() {throw new Error('Unsigned command reached host');}});
    vm.runInContext(fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/auth.js'), 'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/pairing.js'), 'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(root, 'cep/com.mikechambers.an/main.js'), 'utf8'), context);
    await elements.btnConnect.click();
    assert.equal(elements.statusText.textContent, 'Disconnected');
    assert.equal(captured.length, 1); assert.equal(captured[0].body, '{}');
    assert.ok(captured[0].url.endsWith('/v1/panel/hello'));
    assert.ok(!JSON.stringify(captured).includes('a'.repeat(64)));
    assert.ok(elements.messageLog.value.includes('authentication failed'));
});
test('real Python bridge, WebCrypto panel and Python MCP adapter interoperate', {timeout: 10000}, async () => {
    const crypto = require('node:crypto'), http = require('node:http'), os = require('node:os');
    const {spawn} = require('node:child_process');
    const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'animate-safe-test-')));
    const configFile = path.join(directory, 'private.json');
    const config = {client_token: 'a'.repeat(64), panel_token: 'b'.repeat(64), output_dir: path.join(directory,'exports'), port: 3099, allow_scripts: false, ffmpeg_path: null};
    fs.writeFileSync(configFile, JSON.stringify(config), {mode: 0o600});
    const python = process.env.ANIMATE_TEST_PYTHON || 'python3';
    const server = spawn(python, ['-u','-c', 'from config import load_config; from bridge import Server; s=Server(load_config(),port=0); print(s.server_port,flush=True); s.serve_forever()'], {cwd: path.join(root,'mcp'), env: {...process.env, ANIMATE_MCP_CONFIG: configFile}});
    const requests = new Set(); let clicked = false;
    try {
        const port = await new Promise((resolve, reject) => {server.stdout.once('data', b => resolve(Number(b.toString().trim()))); server.once('error', reject); server.once('exit', code => reject(new Error('Bridge exited: ' + code)));});
        assert.ok(port > 0); config.port = port; fs.writeFileSync(configFile, JSON.stringify(config), {mode: 0o600});
        const elements = {};
        for (const id of ['btnConnect','statusText','messageLog','pairToken','port','pairFile']) elements[id] = {value: '', textContent: '', addEventListener(event, fn) {this[event] = fn;}};
        elements.pairToken.value = config.panel_token; elements.port.value = String(port);
        const context = vm.createContext({setTimeout, clearTimeout, TextEncoder, window: {crypto: crypto.webcrypto, addEventListener() {}, confirm() {return false;}}, document: {getElementById: id => elements[id]},
            XMLHttpRequest: function () {
                this.headers = {'Origin': 'file://'}; this.open = (method, url) => {this.url = url;};
                this.setRequestHeader = (name, value) => {this.headers[name] = value;};
                this.getResponseHeader = name => this.responseHeaders[name.toLowerCase()] || null;
                this.send = body => {
                    const req = http.request(this.url, {method: 'POST', headers: {...this.headers,'Content-Length':Buffer.byteLength(body)}}, response => {
                        let raw = ''; response.setEncoding('utf8'); response.on('data', chunk => {raw += chunk;});
                        response.on('end', () => {this.status = response.statusCode; this.responseText = raw; this.responseHeaders = response.headers; this.onload();});
                    });
                    requests.add(req); req.on('close', () => requests.delete(req)); req.on('error', () => this.onerror()); req.end(body);
                };
            }, executePacket(packet, session, allow) {
                assert.equal(packet.session, session); assert.equal(allow, false); assert.equal(packet.action, 'getDocuments');
                return Promise.resolve({ok: true, data: []});
            }});
        vm.runInContext(fs.readFileSync(path.join(root,'cep/com.mikechambers.an/auth.js'),'utf8'), context);
        vm.runInContext(fs.readFileSync(path.join(root,'cep/com.mikechambers.an/pairing.js'),'utf8'), context);
        vm.runInContext(fs.readFileSync(path.join(root,'cep/com.mikechambers.an/main.js'),'utf8'), context);
        await elements.btnConnect.click(); clicked = true;
        assert.equal(elements.statusText.textContent, 'Connected · bounded operations'); assert.equal(elements.pairToken.value, '');
        const client = spawn(python, ['-c', 'import importlib.util,json; from config import load_config; s=importlib.util.spec_from_file_location("adapter","an-mcp.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.request(load_config(),"getDocuments",{})))'], {cwd: path.join(root,'mcp'), env: {...process.env, ANIMATE_MCP_CONFIG: configFile}});
        const output = await new Promise((resolve,reject) => {let out='',err=''; client.stdout.on('data', b => {out += b;}); client.stderr.on('data', b => {err += b;}); client.on('error',reject); client.on('exit', code => code === 0 ? resolve(out) : reject(new Error(err)));});
        assert.deepEqual(JSON.parse(output), []);
        await elements.btnConnect.click(); assert.equal(elements.statusText.textContent, 'Disconnected');
    } finally {
        for (const req of requests) req.destroy();
        server.kill(); await new Promise(resolve => server.once('exit', resolve)); fs.rmSync(directory, {recursive:true,force:true});
    }
});
test('pairing-file chooser accepts only bounded local panel credentials and never auto-connects', () => {
    const elements = {}, read = [];
    for (const id of ['btnConnect','statusText','messageLog','pairToken','port','pairFile'])
        elements[id] = {value: '', textContent: '', addEventListener(event, fn) {this[event] = fn;}};
    const context = vm.createContext({setTimeout, clearTimeout, document: {getElementById: id => elements[id]},
        window: {addEventListener() {}}, FileReader: function () {
            this.readAsText = file => {read.push(file); this.result = file.text; this.onload();};
        }});
    vm.runInContext(fs.readFileSync(path.join(root,'cep/com.mikechambers.an/pairing.js'),'utf8'), context);
    vm.runInContext(fs.readFileSync(path.join(root,'cep/com.mikechambers.an/main.js'),'utf8'), context);
    const valid = {panel_token: 'c'.repeat(64), port: 3099};
    elements.pairFile.files = [{size: 100, text: JSON.stringify(valid)}];
    elements.pairFile.change();
    assert.equal(elements.pairToken.value, valid.panel_token);
    assert.equal(elements.port.value, '3099');
    assert.ok(!elements.messageLog.value.includes(valid.panel_token));
    assert.notEqual(elements.statusText.textContent, 'Connected · bounded operations');
    elements.pairToken.value = '';
    for (const data of [{...valid, client_token: 'd'.repeat(64)}, {...valid, port: 80}, {...valid, panel_token: 'bad'}]) {
        elements.pairFile.files = [{size: 100, text: JSON.stringify(data)}]; elements.pairFile.change();
        assert.equal(elements.pairToken.value, '');
    }
    const previous = read.length;
    elements.pairFile.files = [{size: 4097, text: JSON.stringify(valid)}]; elements.pairFile.change();
    assert.equal(read.length, previous);
});
