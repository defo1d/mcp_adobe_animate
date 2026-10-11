"""Mutual authentication for local HTTP; secrets never travel as bearer credentials."""
import hashlib
import hmac
import json
import math
import re
import secrets
import time


def strict_json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite number')
        return result
    def invalid(_):
        raise ValueError('Non-finite number')
    return json.loads(raw, object_pairs_hook=unique, parse_float=number, parse_constant=invalid)


def request_signature(token, method, host, path, stamp, nonce, body, instance='hello'):
    prefix = '\n'.join(('animate-mcp-safe-request-v1', method, host, path, instance, stamp, nonce)) + '\n'
    return hmac.new(bytes.fromhex(token), prefix.encode('ascii') + body, hashlib.sha256).hexdigest()


def request_headers(token, host, path, body, nonce=None, stamp=None, instance='hello'):
    nonce = nonce or secrets.token_hex(16)
    stamp = stamp or str(int(time.time()))
    return {'Authorization': 'HMAC ' + request_signature(token, 'POST', host, path, stamp, nonce, body, instance),
            'X-Animate-Nonce': nonce, 'X-Animate-Timestamp': stamp, 'X-Animate-Instance': instance}


def check_request(token, method, host, path, body, authorization, stamp, nonce, instance='hello'):
    if (not isinstance(nonce, str) or not re.fullmatch('[0-9a-f]{32}', nonce)
            or not isinstance(stamp, str) or not re.fullmatch('[0-9]{9,12}', stamp)
            or abs(time.time() - int(stamp)) > 30
            or not isinstance(authorization, str) or not re.fullmatch('HMAC [0-9a-f]{64}', authorization)):
        return False
    return hmac.compare_digest(authorization[5:], request_signature(token, method, host, path, stamp, nonce, body, instance))


def response_signature(token, nonce, status, body):
    prefix = 'animate-mcp-safe-response-v1\n' + nonce + '\n' + str(status) + '\n'
    return hmac.new(bytes.fromhex(token), prefix.encode('ascii') + body, hashlib.sha256).hexdigest()


def check_response(token, nonce, status, body, signature):
    if (not isinstance(signature, str) or not re.fullmatch('[0-9a-f]{64}', signature)
            or not hmac.compare_digest(signature, response_signature(token, nonce, status, body))):
        raise ValueError('Local server authentication failed; response rejected')
