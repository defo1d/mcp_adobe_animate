/* SPDX-License-Identifier: MIT
 * Project-owned adapter for the two native CEP operations used by this panel.
 * This is not the Adobe CSInterface SDK and does not implement its other APIs.
 */
'use strict';
(function (scope) {
    function nativeHost(operation) {
        const host = scope.__adobe_cep__;
        if (!host || typeof host[operation] !== 'function')
            throw new Error('Required Adobe CEP operation is unavailable');
        return host;
    }
    function PanelHost() {}
    PanelHost.prototype.evalScript = function (source, callback) {
        if (typeof source !== 'string' || typeof callback !== 'function')
            throw new Error('Invalid host execution arguments');
        const host = nativeHost('evalScript');
        host.evalScript(source, callback);
    };
    PanelHost.prototype.getSystemPath = function (type) {
        if (type !== 'userData') throw new Error('Unsupported system path');
        const host = nativeHost('getSystemPath');
        const encoded = host.getSystemPath(type);
        if (typeof encoded !== 'string') throw new Error('Invalid Adobe user data path');
        let value = decodeURI(encoded);
        if (value.startsWith('file://')) value = value.slice(7);
        if (!value.startsWith('/') || /[\u0000-\u001f\u007f]/.test(value))
            throw new Error('Invalid macOS user data path');
        return value;
    };
    scope.SystemPath = Object.freeze({USER_DATA: 'userData'});
    scope.CSInterface = PanelHost;
}(window));
