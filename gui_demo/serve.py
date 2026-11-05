"""Serve the self-contained FAIRY UI on loopback without installing packages."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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
