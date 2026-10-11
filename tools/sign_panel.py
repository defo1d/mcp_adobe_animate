#!/usr/bin/env python3
"""Offline CEP XMLDSig packager using macOS OpenSSL and libxml2.

No downloaded executable, trust-store changes, debug-mode switches or network.
Only signs this repository's panel. Private signing material stays outside it.
"""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile

NS = 'http://www.w3.org/2000/09/xmldsig#'
C14N = 'http://www.w3.org/TR/2001/REC-xml-c14n-20010315'
SHA256 = 'http://www.w3.org/2001/04/xmlenc#sha256'
ET.register_namespace('', NS)


def command(args, data=None):
    return subprocess.run(args, input=data, capture_output=True, check=True,
                          timeout=30, env={'PATH': '/usr/bin:/bin'}).stdout


def canonical(element):
    return command(['/usr/bin/xmllint', '--nonet', '--c14n', '-'],
                   ET.tostring(element, encoding='utf-8'))


def child(parent, name, attrs=None, text=None):
    e = ET.SubElement(parent, '{' + NS + '}' + name, attrs or {})
    e.text = text
    return e


def digest(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--signing-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--legacy-cep-signature', action='store_true',
                    help='Use Adobe UCF RSA-SHA1 signature format; file digests remain SHA256')
    args = ap.parse_args()
    os.umask(0o077)
    root = args.signing_dir
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('Absolute private signing directory required')
    root.mkdir(mode=0o700, exist_ok=True)
    st = root.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('Signing directory must be private and owned by you')
    key, cert = root / 'key.pem', root / 'certificate.pem'
    if not key.exists() and not cert.exists():
        command(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:3072',
                 '-sha256', '-nodes', '-days', '365', '-subj',
                 '/CN=Animate MCP Safe Local/O=Local Development',
                 '-keyout', str(key), '-out', str(cert)])
    for p in (key, cert):
        if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
            raise ValueError('Unsafe signing material')
    panel = Path(__file__).resolve().parents[1] / 'cep/com.mikechambers.an'
    files = {'mimetype': b'application/vnd.adobe.air-ucf-package+zip'}
    for p in sorted(panel.rglob('*')):
        if p.is_symlink():
            raise ValueError('Panel must not contain symlinks')
        if p.is_file():
            name = p.relative_to(panel).as_posix()
            if name.startswith('META-INF/') or name.startswith('.'):
                raise ValueError('Unexpected panel file')
            files[name] = p.read_bytes()
    manifest = ET.Element('{' + NS + '}Manifest', {'Id': 'PackageContents'})
    for name, data in files.items():
        ref = child(manifest, 'Reference', {'URI': name})
        child(ref, 'DigestMethod', {'Algorithm': SHA256})
        child(ref, 'DigestValue', text=digest(data))
    signature = ET.Element('{' + NS + '}Signature', {'Id': 'PackageSignature'})
    info = child(signature, 'SignedInfo')
    child(info, 'CanonicalizationMethod', {'Algorithm': C14N})
    signature_hash = 'sha1' if args.legacy_cep_signature else 'sha256'
    method = NS + 'rsa-sha1' if args.legacy_cep_signature else 'http://www.w3.org/2001/04/xmldsig-more#rsa-sha256'
    child(info, 'SignatureMethod', {'Algorithm': method})
    ref = child(info, 'Reference', {'Type': NS + 'Manifest', 'URI': '#PackageContents'})
    transforms = child(ref, 'Transforms')
    child(transforms, 'Transform', {'Algorithm': C14N})
    child(ref, 'DigestMethod', {'Algorithm': SHA256})
    child(ref, 'DigestValue', text=digest(canonical(manifest)))
    signed = canonical(info)
    sig = command(['/usr/bin/openssl', 'dgst', '-' + signature_hash, '-sign', str(key)], signed)
    child(signature, 'SignatureValue', {'Id': 'PackageSignatureValue'}, base64.b64encode(sig).decode())
    ki = child(signature, 'KeyInfo')
    xd = child(ki, 'X509Data')
    der = command(['/usr/bin/openssl', 'x509', '-in', str(cert), '-outform', 'DER'])
    child(xd, 'X509Certificate', text=base64.b64encode(der).decode())
    child(signature, 'Object').append(manifest)
    # The UCF container element is outside the XMLDSig namespace.
    # Adobe's UCF parser requires the literal container at byte zero.
    xml = (b'<signatures>' +
           ET.tostring(signature, encoding='utf-8', short_empty_elements=False) + b'</signatures>')
    # Verify the serialized data independently before writing the package.
    parsed = ET.fromstring(xml)
    actual_info = parsed.find('.//{' + NS + '}SignedInfo')
    actual_manifest = parsed.find('.//{' + NS + '}Manifest')
    assert canonical(actual_info) == signed
    assert digest(canonical(actual_manifest)) == ref.find('{' + NS + '}DigestValue').text
    public = command(['/usr/bin/openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'])
    (root / 'public.pem').write_bytes(public)
    (root / 'signature.bin').write_bytes(sig)
    verified = command(['/usr/bin/openssl', 'dgst', '-' + signature_hash, '-verify', str(root / 'public.pem'),
                        '-signature', str(root / 'signature.bin')], signed)
    if b'Verified OK' not in verified:
        raise ValueError('Signature verification failed')
    files['META-INF/signatures.xml'] = xml
    if not args.output.is_absolute() or args.output.is_symlink():
        raise ValueError('Absolute new output path required')
    with zipfile.ZipFile(args.output, 'x') as z:
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED)
    print('Signed package:', args.output)
    print('SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())
    print('Self-signed local certificate; expires after 365 days. No trust-store installation.')


if __name__ == '__main__':
    main()
