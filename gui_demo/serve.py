"""Serve the self-contained FAIRY UI on loopback without installing packages."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
from urllib.parse import urlsplit


GUIDANCE_API = '/api/knowledge-guidance'
MAX_GUIDANCE_REQUEST_BYTES = 1024 * 1024


class GuidanceStoreError(ValueError):
    """The existing guidance file cannot safely be read or extended."""


class KnowledgeGuidanceStore:
    """Append plain text with authoritative IDs, serialized by storage path.

    Empty/missing files represent an empty collection. Nonempty malformed files
    are never replaced. The shared lock covers read/number/write even when a
    request handler creates a fresh store object for the same server root.
    """

    _locks = {}
    _locks_guard = Lock()

    def __init__(self, root):
        self.path = Path(root).resolve() / 'Knowledge_Guidance' / 'expert_guidance.json'
        with self._locks_guard:
            self._lock = self._locks.setdefault(self.path, Lock())

    @staticmethod
    def next_key(entries):
        largest = max((int(key.removeprefix('expert_guidance_')) for key in entries), default=-1)
        return f'expert_guidance_{largest + 1:03d}'

    def _read_locked(self):
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return {}
        except UnicodeError as error:
            raise GuidanceStoreError('The guidance file is not valid UTF-8; existing data was left unchanged.') from error
        if not raw.strip():
            return {}

        def unique_keys(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise GuidanceStoreError('The guidance file contains duplicate keys; existing data was left unchanged.')
                value[key] = item
            return value

        try:
            entries = json.loads(raw, object_pairs_hook=unique_keys)
        except json.JSONDecodeError as error:
            raise GuidanceStoreError('The guidance file contains invalid JSON; existing data was left unchanged.') from error
        if not isinstance(entries, dict) or any(
            not isinstance(key, str) or not re.fullmatch(r'expert_guidance_[0-9]+', key)
            or not isinstance(value, str)
            for key, value in entries.items()
        ):
            raise GuidanceStoreError('The guidance file must be an object of expert_guidance_NNN keys and text values; existing data was left unchanged.')
        return entries

    def read(self):
        with self._lock:
            entries = self._read_locked()
            return {'entries': entries, 'next_key': self.next_key(entries)}

    def append(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Guidance text must contain at least one non-whitespace character.')
        with self._lock:
            entries = self._read_locked()
            key = self.next_key(entries)
            entries[key] = text
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Keep a failed temporary write for diagnosis instead of deleting
            # it. Only a fully flushed file replaces the previous JSON file.
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.path.parent,
                prefix='.expert-guidance-', suffix='.tmp', delete=False,
            ) as temporary:
                json.dump(entries, temporary, ensure_ascii=False, indent=2)
                temporary.write('\n')
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
            return {'key': key, 'value': text, 'next_key': self.next_key(entries)}


class DemoRequestHandler(SimpleHTTPRequestHandler):
    # Browser modules need a JavaScript MIME type even when a platform's MIME
    # registry associates .js with another application (notably on Windows).
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.js': 'text/javascript',
        '.mjs': 'text/javascript',
        '.json': 'application/json',
        '.css': 'text/css',
        '.svg': 'image/svg+xml',
    }

    def __init__(self, *args, directory=None, **kwargs):
        root = Path(directory) if directory is not None else Path(__file__).resolve().parent
        self.guidance_store = KnowledgeGuidanceStore(root)
        super().__init__(*args, directory=str(root), **kwargs)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _api_error(self, status, code, message):
        self._send_json(status, {'error': code, 'message': message})

    def _valid_local_request(self, check_origin=False):
        """Accept the current loopback origin, without adding a CORS endpoint."""
        try:
            host = urlsplit('http://' + self.headers.get('Host', ''))
            port = host.port or 80
        except ValueError:
            return False
        if host.hostname not in ('127.0.0.1', 'localhost', '::1') or port != self.server.server_port or host.username or host.password or host.path:
            return False
        origin_value = self.headers.get('Origin')
        if not check_origin or origin_value is None:
            return True
        try:
            origin = urlsplit(origin_value)
            origin_port = origin.port or (80 if origin.scheme == 'http' else 443)
        except ValueError:
            return False
        return (
            origin.scheme == 'http' and origin.hostname == host.hostname
            and origin_port == port and not origin.username and not origin.password
            and not origin.path and not origin.query and not origin.fragment
        )

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == GUIDANCE_API:
            if not self._valid_local_request():
                self._api_error(403, 'invalid_host', 'Use this API through the current localhost server.')
                return
            try:
                self._send_json(200, self.guidance_store.read())
            except GuidanceStoreError as error:
                self._api_error(409, 'invalid_store', str(error))
            except OSError:
                self._api_error(500, 'storage_error', 'The guidance file could not be read. Check local file permissions.')
            return
        if path.startswith('/api/'):
            self._api_error(404, 'not_found', 'API endpoint not found.')
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != GUIDANCE_API:
            self._api_error(404, 'not_found', 'API endpoint not found.')
            return
        if not self._valid_local_request(check_origin=True):
            self._api_error(403, 'invalid_origin', 'Guidance must be submitted from the current localhost page.')
            return
        if self.headers.get_content_type() != 'application/json':
            self._api_error(415, 'unsupported_media_type', 'Send guidance as application/json.')
            return
        length_header = self.headers.get('Content-Length')
        if length_header is None:
            self._api_error(411, 'length_required', 'Content-Length is required.')
            return
        try:
            length = int(length_header)
        except ValueError:
            length = -1
        if length < 0:
            self._api_error(400, 'invalid_length', 'Content-Length must be a nonnegative integer.')
            return
        if length > MAX_GUIDANCE_REQUEST_BYTES:
            self._api_error(413, 'request_too_large', 'Guidance requests must be at most 1 MiB.')
            return
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError):
            self._api_error(400, 'invalid_json', 'The request body must contain valid UTF-8 JSON.')
            return
        if not isinstance(payload, dict) or set(payload) != {'text'} or not isinstance(payload['text'], str) or not payload['text'].strip():
            self._api_error(400, 'invalid_text', 'Send an object with one nonempty text field.')
            return
        try:
            result = self.guidance_store.append(payload['text'])
        except GuidanceStoreError as error:
            self._api_error(409, 'invalid_store', str(error))
        except OSError:
            self._api_error(500, 'storage_error', 'Guidance could not be saved. Existing data is unchanged; an incomplete temporary file may remain.')
        else:
            self._send_json(201, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4177)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    handler = partial(DemoRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'FAIRY 2.0: http://127.0.0.1:{server.server_port}', flush=True)
    print('Press Ctrl+C to stop. No simulation or model server is started.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
