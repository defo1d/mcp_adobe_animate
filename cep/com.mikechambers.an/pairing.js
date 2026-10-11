/* Optional local startup pairing. Reads one fixed private file, never tool input. */
'use strict';
const AnimatePairing = (function () {
    function validate(text) {
        if (typeof text !== 'string' || text.length > 4096) throw new Error('Invalid pairing file');
        const data = JSON.parse(text);
        if (!data || Object.keys(data).sort().join(',') !== 'panel_token,port' ||
            typeof data.panel_token !== 'string' || !/^[0-9a-f]{64}$/.test(data.panel_token) ||
            !Number.isInteger(data.port) || data.port < 1024 || data.port > 65535)
            throw new Error('Invalid pairing file');
        return data;
    }
    function readFixedFile(userData) {
        // Serialized into Animate's ES5 JSFL. No configurable path or evaluated file content.
        var home = typeof userData === 'string' && /^\/Users\/([^/\u0000-\u001f]+)(?:\/|$)/.exec(userData);
        if (!home || home[1] === '.' || home[1] === '..') return '';
        var uri = FLfile.platformPathToURI('/Users/' + home[1] + '/Library/Application Support/Animate MCP Safe/auto-pairing.json');
        if (!FLfile.exists(uri)) return '';
        var size = Number(FLfile.getSize(uri));
        if (!isFinite(size) || size <= 0 || size > 4096) return '';
        return FLfile.read(uri) || '';
    }
    function loadAuto() {
        if (typeof CSInterface !== 'function' || typeof SystemPath === 'undefined') return Promise.resolve(null);
        return new Promise(function (resolve) {
            const host = new CSInterface();
            const userData = host.getSystemPath(SystemPath.USER_DATA);
            const literal = JSON.stringify(userData).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
            host.evalScript('(' + readFixedFile.toString() + ')(' + literal + ')', function (text) {
                if (!text) { resolve(null); return; }
                try { resolve(validate(text)); } catch (_) { resolve(null); }
            });
        });
    }
    function createRetry(attempt, schedule, cancel) {
        // Retry authentication only. Commands are never held or replayed here.
        schedule = schedule || setTimeout; cancel = cancel || clearTimeout;
        let timer = null, busy = false, generation = 0, delay = 1000;
        function stop() {
            generation++;
            if (timer !== null) cancel(timer);
            timer = null; busy = false;
        }
        async function run(current) {
            if (current !== generation) return;
            busy = true;
            let done = false;
            try { done = await attempt(); } catch (_) {}
            if (current !== generation) return;
            busy = false;
            if (done === true) return;
            timer = schedule(function () { timer = null; run(current); }, delay);
            delay = Math.min(delay * 2, 30000);
        }
        function start() {
            if (busy || timer !== null) return;
            delay = 1000;
            run(++generation);
        }
        return Object.freeze({start: start, stop: stop});
    }
    return Object.freeze({validate: validate, loadAuto: loadAuto, createRetry: createRetry});
}());
