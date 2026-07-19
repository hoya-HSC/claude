from __future__ import annotations

import argparse

from .config import load_config
from .db import connect


def main() -> None:
    parser = argparse.ArgumentParser(prog="photomanager")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Scan and process one batch (scan -> metadata -> faces -> events)")
    run_parser.add_argument("--roots", nargs="+", required=True, help="Directories to scan")
    run_parser.add_argument("--no-faces", action="store_true", help="Skip face detection (metadata/events only)")

    serve_parser = sub.add_parser("serve", help="Start the review web UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "run":
        from . import pipeline

        cfg.scan_roots = args.roots
        embedder = None
        if not args.no_faces:
            from .faces import FaceEmbedder
            embedder = FaceEmbedder()

        conn = connect(cfg.db_path)
        try:
            stats = pipeline.run_once(conn, cfg, embedder=embedder)
            print(
                f"scanned: {len(stats.scanned.new_files)} new, "
                f"{stats.scanned.moved_files} moved, "
                f"{stats.scanned.unchanged_files} unchanged, "
                f"{stats.scanned.missing_files} missing"
            )
            print(f"metadata processed: {stats.metadata_processed}")
            print(f"faces processed: {stats.faces_processed}")
            print(f"events: {stats.events_rebuilt}")
        finally:
            conn.close()

    elif args.command == "serve":
        import uvicorn

        uvicorn.run("photomanager.web.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
