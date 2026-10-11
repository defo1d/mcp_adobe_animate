'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../cep/com.mikechambers.an/pairing.js'),'utf8');

function harness(userData, data, size = Buffer.byteLength(data)) {
    const paths = [];
    const host = vm.createContext({FLfile: {
        platformPathToURI(p) {paths.push(p); return 'file://' + p;},
        exists() {return true;}, getSize() {return size;}, read() {return data;}
    }});
    const context = vm.createContext({});
    context.window = context;
    context.__adobe_cep__ = {
        getSystemPath(p) {assert.equal(p, 'userData'); return userData;},
        evalScript(s, cb) {cb(vm.runInContext(s, host));}
    };
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../cep/com.mikechambers.an/host.js'), 'utf8'), context);
    vm.runInContext(source,context);
    return {pairing: vm.runInContext('AnimatePairing',context), paths, host};
}
test('startup pairing reads only the fixed local opt-in file', async () => {
    const value = {panel_token:'c'.repeat(64),port:3099};
    const h = harness('/Users/test/Library/Application Support',JSON.stringify(value));
    assert.equal(JSON.stringify(await h.pairing.loadAuto()),JSON.stringify(value));
    assert.deepEqual(h.paths,['/Users/test/Library/Application Support/Animate MCP Safe/auto-pairing.json']);
    const adobe = harness('/Users/test/Library/Application Support/Adobe',JSON.stringify(value));
    assert.ok(await adobe.pairing.loadAuto());
    assert.deepEqual(adobe.paths,h.paths);
});
test('oversized, invalid and broader credential files are rejected without evaluating their contents', async () => {
    for (const text of ['fl.injected=true;',JSON.stringify({panel_token:'c'.repeat(64),port:3099,client_token:'d'.repeat(64)}),'{}']) {
        const h=harness('/Users/test/Library/Application Support',text);
        assert.equal(await h.pairing.loadAuto(),null); assert.equal(h.host.fl,undefined);
    }
    const h=harness('/Users/test/Library/Application Support',JSON.stringify({panel_token:'c'.repeat(64),port:3099}),4097);
    assert.equal(await h.pairing.loadAuto(),null);
});
test('unsupported roots fail closed and platform path characters remain literal data', async () => {
    for (const root of ['/tmp','/Users/../Library/Application Support','/Volumes/private']) {
        const h=harness(root,'{}'); assert.equal(await h.pairing.loadAuto(),null); assert.equal(h.paths.length,0);
    }
    const root='/Users/a";fl.injected=true;//\u2028/Library/Application Support';
    const h=harness(root,JSON.stringify({panel_token:'c'.repeat(64),port:3099}));
    assert.ok(await h.pairing.loadAuto()); assert.equal(h.host.fl,undefined);
    assert.equal(h.paths[0],'/Users/'+root.split('/')[2]+'/Library/Application Support/Animate MCP Safe/auto-pairing.json');
});

function retryHarness(attempt) {
    const pairing = harness('/tmp','{}').pairing;
    const pending = new Map(), delays = [], cancelled = [];
    let sequence = 0;
    const retry = pairing.createRetry(attempt,(fn,delay) => {
        delays.push(delay); pending.set(++sequence,fn); return sequence;
    }, id => {cancelled.push(id); pending.delete(id);});
    const flush = async () => {for(let i=0;i<8;i++) await Promise.resolve();};
    return {retry,pending,delays,cancelled,flush};
}
test('authentication retry is serial, uses bounded backoff and stops after success', async () => {
    let calls=0;
    const h=retryHarness(async () => ++calls===9);
    h.retry.start(); h.retry.start(); await h.flush();
    assert.equal(calls,1); assert.equal(h.pending.size,1);
    while(h.pending.size) {
        const [id,fn]=h.pending.entries().next().value; h.pending.delete(id); fn();
        await h.flush(); assert.ok(h.pending.size<=1);
    }
    assert.equal(calls,9);
    assert.deepEqual(h.delays,[1000,2000,4000,8000,16000,30000,30000,30000]);
});
test('manual stop cancels pending authentication and makes stale callbacks harmless', async () => {
    let calls=0;
    const h=retryHarness(async () => {calls++;return false;});
    h.retry.start(); await h.flush();
    const fn=h.pending.values().next().value;
    h.retry.stop(); assert.equal(h.pending.size,0); assert.equal(h.cancelled.length,1);
    fn(); await h.flush(); assert.equal(calls,1); assert.equal(h.pending.size,0);
});
test('stopping an in-flight attempt prevents rescheduling; explicit new startup works', async () => {
    let resolve, calls=0;
    const h=retryHarness(() => {calls++;return new Promise(r=>{resolve=r;});});
    h.retry.start(); h.retry.stop(); resolve(false); await h.flush();
    assert.equal(h.pending.size,0);
    h.retry.start(); assert.equal(calls,2); resolve(true); await h.flush();
    assert.equal(h.pending.size,0);
});

test('manual pairing cancels a delayed automatic registration before polling can start', async () => {
    const crypto=require('node:crypto'), elements={}, requests=[];
    for(const id of ['btnConnect','statusText','messageLog','pairToken','port','pairFile'])
        elements[id]={value:'',textContent:'',addEventListener(event,fn){this[event]=fn;}};
    const pairing=harness('/tmp','{}').pairing, credentials={panel_token:'c'.repeat(64),port:3099};
    const retry=pairing.createRetry;
    const context=vm.createContext({document:{getElementById:id=>elements[id]},
        window:{crypto:crypto.webcrypto,addEventListener(){}},
        AnimatePairing:{validate:pairing.validate,loadAuto:async()=>credentials,
            createRetry:attempt=>retry(attempt,()=>{throw new Error('Cancelled registration rescheduled');},()=>{})},
        AnimateAuth:{request:async()=>({authorization:'HMAC proof',nonce:'d'.repeat(32),stamp:'0'}),verify:async()=>{}},
        FileReader:function(){this.readAsText=file=>{this.result=file.text;this.onload();};},
        XMLHttpRequest:function(){
            this.open=(method,url)=>{this.url=url;};this.setRequestHeader=()=>{};this.getResponseHeader=()=>'';
            this.send=()=>{
                requests.push(this);
                if(this.url.endsWith('/hello')){
                    this.status=200;this.responseText=JSON.stringify({ok:true,data:{instance:'e'.repeat(32)}});this.onload();
                }
            };
        },executePacket(){throw new Error('Unexpected command');}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../cep/com.mikechambers.an/main.js'),'utf8'),context);
    for(let i=0;i<30;i++)await Promise.resolve();
    const registration=requests.find(r=>r.url.endsWith('/register'));assert.ok(registration);
    const manual={panel_token:'f'.repeat(64),port:3100};
    elements.pairFile.files=[{size:100,text:JSON.stringify(manual)}];elements.pairFile.change();
    registration.status=200;registration.responseText=JSON.stringify({ok:true,data:{allow_scripts:false}});registration.onload();
    for(let i=0;i<30;i++)await Promise.resolve();
    assert.equal(elements.statusText.textContent,'Disconnected');
    assert.equal(elements.pairToken.value,manual.panel_token);
    assert.equal(elements.btnConnect.textContent,'Connect');
    assert.ok(!requests.some(r=>r.url.endsWith('/next')));
});
