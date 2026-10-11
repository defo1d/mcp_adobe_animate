/* WebCrypto-only mutual authentication. Fail closed if unavailable; no bearer fallback. */
'use strict';
const AnimateAuth = (function () {
    function random() {
        const bytes = new Uint8Array(16); window.crypto.getRandomValues(bytes);
        return Array.from(bytes).map(function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    }
    async function signature(token, message) {
        if (!window.crypto || !window.crypto.subtle || typeof TextEncoder === 'undefined')
            throw new Error('WebCrypto unavailable; authenticated mode is required');
        const bytes = new Uint8Array(token.match(/../g).map(function (pair) { return parseInt(pair, 16); }));
        const key = await window.crypto.subtle.importKey('raw', bytes, {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
        const result = await window.crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
        return Array.from(new Uint8Array(result)).map(function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    }
    async function request(token, host, path, body, instance) {
        const nonce = random(), stamp = String(Math.floor(Date.now() / 1000));
        const mac = await signature(token, ['animate-mcp-safe-request-v1', 'POST', host, path, instance, stamp, nonce, body].join('\n'));
        return {nonce: nonce, stamp: stamp, authorization: 'HMAC ' + mac};
    }
    async function verify(token, nonce, status, body, received) {
        const expected = await signature(token, ['animate-mcp-safe-response-v1', nonce, String(status), body].join('\n'));
        if (typeof received !== 'string' || !/^[0-9a-f]{64}$/.test(received) || received !== expected)
            throw new Error('Local server authentication failed; response rejected');
    }
    return {request: request, verify: verify};
}());
