#!/usr/bin/env python3
"""Stage authoring-archive pillar posts as drafts in /admin/blog.

Runs INSIDE the backend container — calls validate_payload + save_draft
directly, bypassing HTTP/auth. The drafts then appear in /admin/blog
exactly as if they had been pasted into the admin form, where the admin
reviews and clicks Publish.

Usage (from your laptop):

    # Stage every archive in docs/blog/ that is not already published
    ssh a11yos-vps "cd /srv/roadmap && \\
      docker compose exec backend python scripts/stage_blog_draft.py --all"

    # Stage specific files (paths are inside the container; docs/blog/
    # is mounted at /app/blog-archives/)
    ssh a11yos-vps "cd /srv/roadmap && \\
      docker compose exec backend python scripts/stage_blog_draft.py \\
        blog-archives/03-ai-engineer-vs-ml-engineer.json \\
        blog-archives/04-learn-ai-without-cs-degree-2026.json"

Then open https://automateedge.cloud/admin/blog and click Publish on
each new draft row.

Exit codes: 0 = all staged, 1 = one or more failed validation,
2 = nothing to do (all already published, --all only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[1]
for _cand in (_HERE, _HERE / "backend"):
    if (_cand / "app" / "services" / "blog_publisher.py").is_file():
        sys.path.insert(0, str(_cand))
        break

from app.services.blog_publisher import (  # noqa: E402
    DRAFTS_DIR,
    PUBLISHED_DIR,
    save_draft,
    validate_payload,
)

ARCHIVE_DIR = Path("/app/blog-archives")


def stage_one(path: Path, admin_name: str, force: bool) -> int:
    name = path.name
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[FAIL] {name}: not valid JSON ({e})")
        return 1
    except OSError as e:
        print(f"[FAIL] {name}: {e}")
        return 1

    slug = (payload.get("slug") or "").strip()
    if not slug:
        print(f"[FAIL] {name}: missing 'slug' field")
        return 1

    already_published = (PUBLISHED_DIR / f"{slug}.json").exists()
    if already_published and not force:
        print(f"[SKIP] {slug}: already PUBLISHED — pass --force to re-stage as draft")
        return 2

    report = validate_payload(payload)
    if not report.get("ok"):
        print(f"[FAIL] {slug}: validator errors")
        for e in report.get("errors") or []:
            print(f"   - {e}")
        return 1

    save_draft(payload, admin_name=admin_name)
    warnings = report.get("warnings") or []
    suffix = ""
    if warnings:
        suffix = f" ({len(warnings)} editorial warning{'s' if len(warnings) != 1 else ''})"
    if already_published and force:
        suffix += " [overwrote published copy via --force]"
    print(f"[OK]   {slug}: staged as draft{suffix}")
    for w in warnings:
        print(f"   ! {w}")
    return 0


def collect_paths(args: argparse.Namespace) -> list[Path]:
    if args.all:
        if not ARCHIVE_DIR.is_dir():
            print(
                f"[FAIL] --all requires {ARCHIVE_DIR} (mount ./docs/blog "
                f"into the container as :ro)",
                file=sys.stderr,
            )
            sys.exit(1)
        return sorted(p for p in ARCHIVE_DIR.glob("*.json") if p.is_file())
    return [Path(p) for p in args.paths]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stage pillar-post JSON archives as /admin/blog drafts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="Pillar-post JSON files (relative paths resolve inside the container)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help=f"Stage every *.json under {ARCHIVE_DIR} (idempotent — skips already-published)",
    )
    ap.add_argument(
        "--admin",
        default="cli (stage_blog_draft.py)",
        help="Reviewer name stamped on the draft (default: %(default)s)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-stage as draft even if already published",
    )
    args = ap.parse_args()

    if not args.all and not args.paths:
        ap.error("supply file paths or pass --all")

    paths = collect_paths(args)
    if not paths:
        print(f"[INFO] no JSON files to stage under {ARCHIVE_DIR}")
        return 2

    ok = skipped = failed = 0
    for raw in paths:
        p = raw if raw.is_absolute() else (ARCHIVE_DIR / raw if not raw.exists() else raw)
        if not p.exists():
            print(f"[FAIL] {raw}: not found (looked at {p})")
            failed += 1
            continue
        rc = stage_one(p, admin_name=args.admin, force=args.force)
        if rc == 0:
            ok += 1
        elif rc == 2:
            skipped += 1
        else:
            failed += 1

    total = ok + skipped + failed
    print(f"\n--- summary: {ok} staged · {skipped} skipped · {failed} failed (of {total}) ---")
    print(f"Drafts written to: {DRAFTS_DIR}")
    print("Next: open https://automateedge.cloud/admin/blog → Publish each new draft row.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
