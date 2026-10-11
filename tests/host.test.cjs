'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../cep/com.mikechambers.an/host.js'), 'utf8');
function adapter(native) {
    const context = vm.createContext({window: {__adobe_cep__: native}});
    vm.runInContext(source, context);
    return {host: new context.window.CSInterface(), paths: context.window.SystemPath};
}
test('native host forwards scripts and callbacks without changing their contents', () => {
    let calls = 0;
    const native = {evalScript(script, callback) {
        assert.equal(this, native); assert.equal(script, 'JSON.stringify(fl.documents.length)');
        calls++; callback('2');
    }};
    const {host} = adapter(native);
    let result;
    host.evalScript('JSON.stringify(fl.documents.length)', value => {result = value;});
    assert.equal(result, '2'); assert.equal(calls, 1);
    assert.throws(() => host.evalScript({}, () => {}));
    assert.throws(() => host.evalScript('return 1', null));
    assert.equal(calls, 1);
});
test('macOS user data paths normalize local file URIs, spaces and Unicode', () => {
    for (const value of ['/Users/test/Library/Application%20Support/Adobe',
        'file:///Users/test/Library/Application%20Support/Adobe',
        'file:///Users/%D1%82%D0%B5%D1%81%D1%82/Library/Application%20Support']) {
        const native = {getSystemPath(type) {assert.equal(this, native); assert.equal(type, 'userData'); return value;}};
        const {host, paths} = adapter(native);
        assert.equal(host.getSystemPath(paths.USER_DATA), decodeURI(value).replace(/^file:\/\//, ''));
        assert.equal(Object.isFrozen(paths), true);
        assert.throws(() => host.getSystemPath('extension'));
    }
});
test('missing CEP operations and malformed paths fail without alternate execution', () => {
    for (const native of [undefined, {}, {evalScript: 'bad'}]) {
        const {host} = adapter(native);
        assert.throws(() => host.evalScript('return 1', () => {}));
        assert.throws(() => host.getSystemPath('userData'));
    }
    for (const value of [null, 4, 'https://host/path', 'file://host/Users/test', '/Users/test\n', '%invalid']) {
        const {host} = adapter({getSystemPath() {return value;}});
        assert.throws(() => host.getSystemPath('userData'));
    }
});
