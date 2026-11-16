"""Serve synthetic recordings without reading the user's Codex directories."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(directory, args):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/review-fixtures.py"),
            "--output",
            str(directory),
            "--schema",
            str(args.schema),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    # The real server reads only these synthetic roots, including fallback discovery.
    os.environ["CODEX_HOME"] = str(directory / "codex-home")
    os.environ["CODEX_ROLLOUT_TRACE_ROOT"] = str(directory / "recordings")
    sys.path.insert(0, str(ROOT / "plugins/codex-dsh-trace/server"))
    import main
    from store import Store

    main.STORE = Store(directory / "viewer-config.json")
    main.preview_server(args.port, args.trace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, help="Keep generated recordings here for live append testing."
    )
    parser.add_argument("--schema", type=int, choices=[1, 2], default=2)
    parser.add_argument("--trace", default="review-rich")
    parser.add_argument("--port", type=int, default=0)
    options = parser.parse_args()
    try:
        if options.directory:
            run(options.directory.resolve(), options)
        else:
            with tempfile.TemporaryDirectory(prefix="codex-trace-demo-") as temporary:
                run(Path(temporary), options)
    except KeyboardInterrupt:
        pass
