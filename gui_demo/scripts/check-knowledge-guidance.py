#!/usr/bin/env python3
"""Exercise knowledge-guidance HTTP persistence using isolated /tmp fixtures.

No production guidance is read or written. Test files are intentionally retained;
this script never deletes files or uses TemporaryDirectory's automatic cleanup.
"""
from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
from functools import partial
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.dont_write_bytecode = True
DEMO_ROOT = Path(__file__).resolve().parents[1]
STORE_RELATIVE = Path("Knowledge_Guidance/expert_guidance.json")
API = "/api/knowledge-guidance"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_store(root):
    return json.loads((root / STORE_RELATIVE).read_text(encoding="utf-8"))


def seed_store(root, value):
    path = root / STORE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return path


def load_service(test_root):
    # Even a future accidental __file__-relative path in serve.py stays isolated.
    source_copy = test_root / "serve_under_test.py"
    source_copy.write_bytes((DEMO_ROOT / "serve.py").read_bytes())
    spec = importlib.util.spec_from_file_location("fairy_guidance_server_under_test", source_copy)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def local_server(module, root):
    root.mkdir(parents=True, exist_ok=True)

    class QuietHandler(module.DemoRequestHandler):
        def log_message(self, *args):
            pass

    class TestServer(module.ThreadingHTTPServer):
        request_queue_size = 64
        daemon_threads = True

    server = TestServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    port = server.server_address[1]

    def request(method="GET", payload=None, *, raw=None, content_type="application/json", origin="same", path=API):
        body = raw if raw is not None else (json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None)
        headers = {}
        if method == "POST":
            headers["Content-Type"] = content_type
        if origin is not None:
            headers["Origin"] = f"http://127.0.0.1:{port}" if origin == "same" else origin
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            try:
                parsed = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                parsed = data.decode("utf-8", errors="replace")
            return response.status, parsed
        finally:
            connection.close()

    try:
        yield request
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        require(not worker.is_alive(), "Test HTTP server did not stop")


def check_missing_and_roundtrip(module, root):
    text = "水稻田间指导 🌾\n第二行：先检查土壤水分。\nKeep this internal newline."
    with local_server(module, root) as request:
        status, result = request()
        require(status == 200 and result == {"entries": {}, "next_key": "expert_guidance_000"}, "Missing store must expose an empty collection and key 000")
        require(not (root / STORE_RELATIVE).exists(), "GET must not create the guidance file")
        status, result = request("POST", {"text": text})
        require(status == 201 and result == {"key": "expert_guidance_000", "value": text, "next_key": "expert_guidance_001"}, "First POST must return the saved Unicode/multiline text and next key")
        status, second = request("POST", {"text": "Second entry"})
        require(status == 201 and second["key"] == "expert_guidance_001" and second["next_key"] == "expert_guidance_002", "Sequential POST keys must advance")
    # Reopen a fresh server to verify persistence, not just a process-local cache.
    with local_server(module, root) as request:
        status, result = request()
        expected = {"expert_guidance_000": text, "expert_guidance_001": "Second entry"}
        require(status == 200 and result["entries"] == expected and result["next_key"] == "expert_guidance_002", "Restarted server must preserve all saved text")
        require(read_store(root) == expected, "Disk file must be the plain key-to-text JSON object")


def check_empty_and_gaps(module, root):
    empty_root = root / "empty"
    path = seed_store(empty_root, b"")
    with local_server(module, empty_root) as request:
        status, result = request()
        require(status == 200 and result == {"entries": {}, "next_key": "expert_guidance_000"}, "Empty file must behave as an empty store")
        require(path.read_bytes() == b"", "Reading an empty store must not rewrite it")
        status, result = request("POST", {"text": "First value in an empty file"})
        require(status == 201 and result["key"] == "expert_guidance_000", "Empty file must accept its first entry")
    gap_root = root / "gaps"
    prior = {"expert_guidance_000": "Keep zero", "expert_guidance_007": "Keep seven"}
    seed_store(gap_root, prior)
    with local_server(module, gap_root) as request:
        status, result = request()
        require(status == 200 and result["next_key"] == "expert_guidance_008", "Next key must use max suffix plus one, not record count or a gap")
        status, result = request("POST", {"text": "Eight"})
        require(status == 201 and result["key"] == "expert_guidance_008", "Gap append must not overwrite existing entries")
        require(read_store(gap_root) == {**prior, "expert_guidance_008": "Eight"}, "Gap append must retain prior records")


def check_concurrent_posts(module, root):
    prior = {"expert_guidance_000": "Existing guidance remains"}
    seed_store(root, prior)
    count = 16
    barrier = threading.Barrier(count)
    with local_server(module, root) as request:
        def post(index):
            barrier.wait(timeout=10)
            text = f"Concurrent instruction {index} · 农事建议"
            status, result = request("POST", {"text": text})
            require(status == 201, f"Concurrent POST {index} failed: {status}, {result}")
            require(result["value"] == text, "Concurrent receipt must belong to its request")
            return result["key"], text

        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
            results = list(executor.map(post, range(count)))
        require(len({key for key, _ in results}) == count, "Concurrent submissions must receive distinct keys")
        require({key for key, _ in results} == {f"expert_guidance_{index:03d}" for index in range(1, count + 1)}, "Concurrent append keys must have no lost increments")
        expected = {**prior, **dict(results)}
        require(read_store(root) == expected, "Concurrent writes must preserve every successful receipt and prior entry")
        status, result = request()
        require(status == 200 and result["entries"] == expected and result["next_key"] == "expert_guidance_017", "GET after concurrent writes must match persisted data")


def check_bad_store_preserved(module, root):
    samples = [b'{"expert_guidance_000":"Keep this", broken}', b'[]', b'{"expert_guidance_000":42}']
    for index, raw in enumerate(samples):
        fixture = root / str(index)
        path = seed_store(fixture, raw)
        with local_server(module, fixture) as request:
            for method, body in [("GET", None), ("POST", {"text": "Must not replace corrupt data"})]:
                status, result = request(method, body)
                require(status == 409 and result.get("error") == "invalid_store", f"Invalid saved JSON/schema must be rejected: {status}, {result}")
                require(path.read_bytes() == raw, "Rejected request must preserve the original malformed bytes")


def check_rejected_requests(module, root):
    path = seed_store(root, {"expert_guidance_000": "Never lose this"})
    original = path.read_bytes()
    with local_server(module, root) as request:
        cases = [
            ({"raw": b"{"}, 400),
            ({"payload": {}}, 400),
            ({"payload": []}, 400),
            ({"payload": {"text": " \t\n\r "}}, 400),
            ({"payload": {"text": 12}}, 400),
            ({"payload": {"text": None}}, 400),
            ({"payload": {"text": "Not JSON media type"}, "content_type": "text/plain"}, 415),
            ({"payload": {"text": "Cross-origin attempt"}, "origin": "https://example.invalid"}, 403),
            ({"payload": {"text": "Opaque-origin attempt"}, "origin": "null"}, 403),
        ]
        for arguments, expected_status in cases:
            status, result = request("POST", **arguments)
            require(status == expected_status and isinstance(result, dict) and result.get("error"), f"Invalid request returned unexpected response: {status}, {result}")
            require(path.read_bytes() == original, "Rejected request must not change persisted bytes")
        status, result = request("POST", {"text": "CLI submission"}, origin=None)
        require(status == 201 and result["key"] == "expert_guidance_001", "Local CLI request without Origin must remain supported")


def check_storage_error(module, root):
    root.mkdir(parents=True, exist_ok=True)
    blocker = root / "Knowledge_Guidance"
    blocker.write_bytes(b"A pre-existing file must not be replaced by a directory")
    original = blocker.read_bytes()
    with local_server(module, root) as request:
        status, result = request("POST", {"text": "Cannot be stored here"})
        require(status == 500 and isinstance(result, dict) and result.get("error"), "Filesystem failure must produce a JSON error, not false success")
        require(blocker.read_bytes() == original, "Filesystem failure must preserve the blocking file")


def check_interrupted_replacement(module, root):
    path = seed_store(root, {"expert_guidance_000": "Prior saved guidance"})
    original = path.read_bytes()
    with local_server(module, root) as request:
        # A failed filesystem commit must not masquerade as a successful save.
        # Only this isolated process is patched; no live server is touched.
        with patch.object(module.os, "replace", side_effect=OSError("Injected commit failure")):
            status, result = request("POST", {"text": "This append must fail"})
        require(status == 500 and result.get("error"), "Failed atomic replacement must return an error")
        require(path.read_bytes() == original, "Failed replacement must preserve the previous file byte for byte")
        status, result = request("POST", {"text": "Recovery append"})
        require(status == 201 and result["key"] == "expert_guidance_001", "A failed commit must not consume an ID")
        require(read_store(root) == {"expert_guidance_000": "Prior saved guidance", "expert_guidance_001": "Recovery append"}, "Recovery must retain prior records and omit the failed append")


def main():
    test_root = Path(tempfile.mkdtemp(prefix="fairy-knowledge-guidance-", dir="/tmp"))
    print(f"Isolated test fixtures retained at: {test_root}", flush=True)
    require(not test_root.resolve().is_relative_to(DEMO_ROOT.resolve()), "Tests must not write inside the demo directory")
    module = load_service(test_root)
    checks = [check_missing_and_roundtrip, check_empty_and_gaps, check_concurrent_posts,
              check_bad_store_preserved, check_rejected_requests, check_storage_error,
              check_interrupted_replacement]
    for check in checks:
        check(module, test_root / check.__name__)
        print(f"PASS {check.__name__}", flush=True)
    print("PASS: knowledge-guidance persistence, concurrency, validation and failure preservation; production data untouched.")


if __name__ == "__main__":
    main()
