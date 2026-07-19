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

    org_parser = sub.add_parser(
        "organize",
        help="Move loose files in a folder into YYYY-MM-DD date subfolders (dry-run by default)",
    )
    org_parser.add_argument("directory", help="Folder whose loose files should be sorted")
    org_parser.add_argument(
        "--apply", action="store_true",
        help="Actually move files. Without this, only a preview is printed.",
    )
    org_parser.add_argument(
        "--list", action="store_true",
        help="List every planned move file-by-file instead of the folder summary.",
    )
    org_parser.add_argument(
        "--report", metavar="CSV",
        help="Write the full plan (every file -> folder, date source) to a CSV file.",
    )

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

    elif args.command == "organize":
        from pathlib import Path

        from . import organize

        directory = Path(args.directory)
        if not directory.is_dir():
            raise SystemExit(f"not a directory: {directory}")

        plan = organize.build_plan(directory, cfg)
        by_source = {"exif": 0, "filename": 0, "mtime": 0}
        for mv in plan.moves:
            by_source[mv.date_source] += 1

        print(f"이동 대상: {len(plan.moves)}개 "
              f"(EXIF/메타 {by_source['exif']}, 파일명 {by_source['filename']}, 수정시간 {by_source['mtime']})")
        print(f"이미 같은 파일 존재(중복, 건너뜀): {len(plan.duplicates)}개")
        print(f"이미 날짜 폴더에 있음: {plan.skipped_already_sorted}개")

        # Per-destination-folder summary, so hundreds of files stay readable.
        from collections import Counter
        folder_counts = Counter(mv.dest.parent.name for mv in plan.moves)
        print(f"\n생성될 날짜 폴더: {len(folder_counts)}개")
        for folder, count in sorted(folder_counts.items()):
            print(f"  {folder}/   {count}개")

        # mtime-dated files are the least reliable (no EXIF, no date in name),
        # so surface those specifically -- they're the ones worth eyeballing.
        mtime_moves = [mv for mv in plan.moves if mv.date_source == "mtime"]
        if mtime_moves:
            print(f"\n※ 수정시간으로 추정된 파일 {len(mtime_moves)}개 (촬영일과 다를 수 있음):")
            for mv in mtime_moves[:15]:
                print(f"  {mv.source.name}  ->  {mv.dest.parent.name}/")
            if len(mtime_moves) > 15:
                print(f"  ... 외 {len(mtime_moves) - 15}개 (전체는 --report 로 CSV 저장)")

        if args.list:
            print("\n[전체 목록]")
            for mv in plan.moves:
                print(f"  {mv.source.name}  ->  {mv.dest.parent.name}/  [{mv.date_source}]")

        if args.report:
            import csv
            with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["파일명", "이동폴더", "날짜판정근거"])
                for mv in plan.moves:
                    writer.writerow([mv.source.name, mv.dest.parent.name, mv.date_source])
            print(f"\n전체 계획을 CSV로 저장: {args.report}")

        if args.apply:
            moved = organize.apply_plan(plan)
            print(f"\n이동 완료: {moved}개")
        else:
            print("\n[미리보기] 실제로 옮기려면 --apply 를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    main()
