"""Check a relocated demo's launchers and HTTP responses without binding a port.

Uses only Python's standard library. The copy is retained for inspection; no
files are deleted. This checks static serving, not browser rendering or WebGL.
"""
import argparse
from email.message import Message
import hashlib
from html.parser import HTMLParser
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

sys.dont_write_bytecode = True


def check_references(root):
    references = set()

    class References(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ('src', 'href') and value:
                    references.add((current, value))

    for current in root.rglob('*'):
        if not current.is_file() or current.suffix not in ('.html', '.js', '.mjs', '.css'):
            continue
        source = current.read_text()
        if current.suffix == '.html':
            References().feed(source)
        for value in re.findall(r'''(?:\bfrom\s*|\bimport\s*)["'](\.[^"']+)["']''', source):
            references.add((current, value))
        # Browser data URLs resolve against the root document. Optional Node
        # utilities contain similar literals but resolve them via their own
        # root variable; do not interpret those as paths beside the script.
        if current.parent == root or current.suffix == '.html':
            for value in re.findall(r'''["']((?:data|assets)/[^"'\s]+\.json)["']''', source):
                references.add((current, value))
    count = 0
    for current, value in references:
        if value.startswith(('#', 'data:', 'http:', 'https:')) or '${' in value:
            continue
        value = value.split('?', 1)[0].split('#', 1)[0]
        target = (root / value.lstrip('/') if value.startswith('/') else current.parent / value).resolve()
        assert target.is_relative_to(root) and target.is_file(), (str(current), value)
        count += 1
    for name in ('index.html', 'app.js', 'serve.py', 'start-demo.command', 'start-demo.bat'):
        assert (root / name).is_file(), name
    return count


def check_http(root):
    spec = importlib.util.spec_from_file_location('relocated_demo_server', root / 'serve.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected_mime = {'.js': 'text/javascript', '.mjs': 'text/javascript',
                     '.json': 'application/json', '.css': 'text/css',
                     '.svg': 'image/svg+xml'}
    suffixes = {'.html', '.js', '.mjs', '.css', '.json', '.svg', '.png',
                '.jpg', '.jpeg', '.webp', '.gif', '.txt'}
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in suffixes)
    total = 0
    for path in files:
        handler = module.DemoRequestHandler.__new__(module.DemoRequestHandler)
        handler.directory = str(root)
        handler.path = '/' + quote(path.relative_to(root).as_posix())
        handler.command = 'GET'
        handler.request_version = 'HTTP/1.1'
        handler.requestline = 'GET ' + handler.path + ' HTTP/1.1'
        handler.headers = Message()
        handler.wfile = BytesIO()
        handler.log_message = lambda *args: None
        handler.do_GET()
        headers, separator, body = handler.wfile.getvalue().partition(b'\r\n\r\n')
        assert separator and b' 200 ' in headers.splitlines()[0], str(path)
        assert hashlib.sha256(body).digest() == hashlib.sha256(path.read_bytes()).digest(), str(path)
        mime = expected_mime.get(path.suffix.lower())
        if mime:
            assert ('Content-type: ' + mime).encode() in headers, str(path)
        total += len(body)
    return len(files), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy-dir', type=Path,
                        help='New directory to retain the relocation test; must not exist.')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if args.copy_dir:
        base = args.copy_dir.resolve()
        if base == source or source in base.parents:
            parser.error('--copy-dir must be outside the source demo')
        base.mkdir(parents=True, exist_ok=False)
    else:
        base = Path(tempfile.mkdtemp(prefix='FAIRY portable check ')).resolve()
    destination = base / 'clone with spaces' / 'gui_demo'
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '.git'))
    working_dir = base / 'different working directory'
    working_dir.mkdir()
    commands = [[sys.executable, str(destination / 'serve.py'), '--help']]
    if os.name == 'posix':
        commands.append([str(destination / 'start-demo.command'), '--help'])
    for command in commands:
        result = subprocess.run(command, cwd=working_dir, check=True,
                                text=True, capture_output=True, timeout=15)
        assert '--port' in result.stdout, command
    reference_count = check_references(destination)
    count, size = check_http(destination)
    print(json.dumps({'copy_retained': str(destination), 'working_directory': str(working_dir),
                      'launcher_help_checks': len(commands), 'local_references_checked': reference_count,
                      'http_resources_checked': count,
                      'http_bytes_checked': size, 'listening_socket_used': False,
                      'windows_batch_executed': False,
                      'browser_rendering_checked': False}, indent=2))


if __name__ == '__main__':
    main()
