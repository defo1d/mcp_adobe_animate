'use strict';
(function () {
    let token = null, session = null, base = null, connected = false, allowScripts = false;
    let connectionEpoch = 0, automaticStopped = false, autoPairingEnabled = false;
    const button = document.getElementById('btnConnect');
    const status = document.getElementById('statusText');
    function log(text) {
        const area = document.getElementById('messageLog');
        area.value = (area.value + text + '\n').slice(-8192);
        area.scrollTop = area.scrollHeight;
    }
    const pairFile = document.getElementById('pairFile');
    pairFile.addEventListener('change', function () {
        const file = pairFile.files[0];
        pairFile.value = '';
        if (connected || !file || file.size > 4096) { log('Select a small private pairing file while disconnected'); return; }
        automaticStopped = true; startup.stop(); reset();
        const reader = new FileReader();
        reader.onload = function () {
            try {
                const data = AnimatePairing.validate(reader.result);
                if (connected) throw new Error('Disconnect before loading credentials');
                document.getElementById('pairToken').value = data.panel_token;
                document.getElementById('port').value = String(data.port);
                log('Pairing file loaded locally. Press Connect.');
            } catch (_) { log('Invalid pairing file; expected only panel_token and port'); }
            finally { reader.onload = null; reader.onerror = null; }
        };
        reader.onerror = function () { log('Could not read pairing file'); };
        reader.readAsText(file);
    });
    async function exchange(path, data, credential, endpoint, instance) {
        const body = JSON.stringify(data);
        const auth = await AnimateAuth.request(credential, endpoint.slice('http://'.length), path, body, instance);
        const response = await new Promise(function (resolve, reject) {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', endpoint + path, true);
            xhr.timeout = 25000;
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.setRequestHeader('Authorization', auth.authorization);
            xhr.setRequestHeader('X-Animate-Nonce', auth.nonce);
            xhr.setRequestHeader('X-Animate-Timestamp', auth.stamp);
            xhr.setRequestHeader('X-Animate-Instance', instance);
            xhr.onload = function () {
                try {
                    if (xhr.responseText.length > 131072) throw new Error('Response too large');
                    resolve({status: xhr.status, body: xhr.responseText, signature: xhr.getResponseHeader('X-Animate-Signature')});
                } catch (error) { reject(error); }
            };
            xhr.onerror = function () { reject(new Error('Local bridge unavailable')); };
            xhr.ontimeout = function () { reject(new Error('Local bridge timeout')); };
            xhr.send(body);
        });
        await AnimateAuth.verify(credential, auth.nonce, response.status, response.body, response.signature);
        const result = JSON.parse(response.body);
        if (response.status !== 200 || !result.ok) throw new Error(result.error || 'Connection rejected');
        return result.data;
    }
    async function request(path, data, credential, endpoint) {
        const hello = await exchange('/v1/panel/hello', {}, credential, endpoint, 'hello');
        if (!hello || typeof hello.instance !== 'string' || !/^[0-9a-f]{32}$/.test(hello.instance))
            throw new Error('Invalid authenticated server identity');
        return exchange(path, data, credential, endpoint, hello.instance);
    }
    function reset() {
        connectionEpoch++;
        connected = false; token = null; session = null; base = null; allowScripts = false;
        button.textContent = 'Connect'; status.textContent = 'Disconnected';
    }
    async function poll(currentSession, credential, endpoint) {
        while (connected && currentSession === session) {
            try {
                const packet = await request('/v1/panel/next', {session: currentSession}, credential, endpoint);
                if (!connected || currentSession !== session) return;
                if (!packet) continue;
                log('Command: ' + packet.action);
                const result = await executePacket(packet, currentSession, allowScripts, function (p) {
                    return window.confirm('Allow this exact JSFL on document ' + p.options.document_id + '?\n\nJSFL can read/write files and change persistent application state. It is not sandboxed.\n\n' + p.options.script);
                });
                if (!connected || currentSession !== session) return;
                await request('/v1/panel/response', {session: currentSession, id: packet.id, result: result}, credential, endpoint);
                log(result.ok ? 'Completed' : 'Failed: ' + String(result.error).slice(0, 256));
            } catch (error) {
                if (currentSession === session) {
                    log(error.message); reset();
                    if (autoPairingEnabled && !automaticStopped) startup.start();
                }
                return; // No command or mutation is retried after reconnecting.
            }
        }
    }
    async function connect(value, port) {
        if (connected) return true;
        if (button.disabled) return false;
        if (!/^[0-9a-f]{64}$/.test(value) || !Number.isInteger(port) || port < 1024 || port > 65535) {
            log('Enter the panel token from your private config and a valid port'); return false;
        }
        button.disabled = true;
        const epoch = connectionEpoch;
        try {
            const random = new Uint8Array(16); window.crypto.getRandomValues(random);
            const candidate = Array.from(random).map(function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
            const endpoint = 'http://127.0.0.1:' + port;
            const result = await request('/v1/panel/register', {session: candidate}, value, endpoint);
            if (epoch !== connectionEpoch) return false;
            token = value; session = candidate; base = endpoint; allowScripts = result.allow_scripts === true; connected = true;
            document.getElementById('pairToken').value = '';
            button.textContent = 'Disconnect'; status.textContent = allowScripts ? 'Connected · JSFL approval mode' : 'Connected · bounded operations';
            poll(session, token, base);
            return true;
        } catch (error) {
            if (epoch === connectionEpoch) { log(error.message); reset(); }
            return false;
        }
        finally { button.disabled = false; }
    }
    button.addEventListener('click', async function () {
        automaticStopped = true; startup.stop();
        if (connected) {
            const oldToken = token, oldSession = session, endpoint = base;
            reset();
            try { await request('/v1/panel/disconnect', {session: oldSession}, oldToken, endpoint); } catch (_) {}
            return;
        }
        await connect(document.getElementById('pairToken').value.trim(), Number(document.getElementById('port').value));
    });
    const startup = AnimatePairing.createRetry(async function () {
        const epoch = connectionEpoch;
        const data = await AnimatePairing.loadAuto();
        if (automaticStopped || epoch !== connectionEpoch) return true;
        if (!data) {
            autoPairingEnabled = false;
            status.textContent = 'Disconnected · startup file unavailable';
            return true;
        }
        autoPairingEnabled = true;
        const success = await connect(data.panel_token, data.port);
        if (!success && !automaticStopped) status.textContent = 'Waiting for local bridge · automatic connection';
        return success;
    });
    window.addEventListener('beforeunload', function () { automaticStopped = true; startup.stop(); reset(); });
    log('Local automatic pairing requires the private auto-pairing.json file. Commands are never replayed.');
    startup.start();
}());
