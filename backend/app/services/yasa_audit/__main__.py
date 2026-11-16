"""Command line entry point.

    python -m app.services.yasa_audit init   <project>             # build codegraph's index of the project
    python -m app.services.yasa_audit recon  <project> --out DIR   # route reconnaissance only
    python -m app.services.yasa_audit run    <project> --out DIR   # recon (reused if DIR/recon exists) + review
    python -m app.services.yasa_audit verify <project> --out DIR   # refutation check of DIR/review/findings.json

LLM settings come from DeepAudit's LLM_BASE_URL / LLM_API_KEY / LLM_MODEL environment variables.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import AuditConfig
from .pipeline import recon, run
from .runner import init_navigation


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.services.yasa_audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "recon", "run", "verify"):
        p = sub.add_parser(name)
        p.add_argument("project", type=Path)
        if name != "init":
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--deploy", default="", help="deployment context, e.g. 'Linux, nginx, PHP 8.3'")
            p.add_argument("--product", default="",
                           help="product context: roles, what is public by design, what input is trusted")
            p.add_argument("--workers", type=int, default=16)
            p.add_argument("--time-budget", type=float, default=30.0,
                           help="wall-clock budget in minutes (default 30); unreviewed entries are listed")
    args = ap.parse_args(argv)
    cfg = AuditConfig()
    root = args.project.resolve()

    if args.cmd == "init":
        init_navigation(cfg, root, timeout_s=3600)
        return 0

    cfg.workers = args.workers
    cfg.time_budget_s = int(args.time_budget * 60)
    start = time.time()
    if args.cmd == "recon":
        result = recon(cfg, root, args.out / "recon", args.deploy, args.product, start + cfg.time_budget_s)
    elif args.cmd == "verify":
        from .verify import verify
        rec_file, rf = args.out / "recon" / "recon.json", args.out / "recon" / "resolver.py"
        rec = json.loads(rec_file.read_text()) if rec_file.exists() else {}
        result = verify(cfg, root, args.out / "review", args.deploy, args.product, rec.get("access_model"),
                        rf.read_text() if rf.exists() else None, start + cfg.time_budget_s)
    else:
        result = run(cfg, root, args.out, args.deploy, args.product, start, start + cfg.time_budget_s)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
