"""Start the single-user farm workbench with a deterministic hash seed."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="FAIRY farm visualization workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("FAIRY_VIS_DATA", str(Path.cwd().parent / "farm-runs"))))
    args = parser.parse_args()
    # Upstream App.set_seed uses hash(); pin it before any scenario import.
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        os.execve(sys.executable, [sys.executable, "-m", "fairy.visualization", *sys.argv[1:]], env)
    import uvicorn
    from .server import create_app
    uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
