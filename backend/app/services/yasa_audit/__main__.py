"""Command line entry point.

    python -m app.services.yasa_audit init  <project>               # build the yasa-mcp navigation cache
    python -m app.services.yasa_audit run   <project> --out DIR     # build rules + engine, then triage
    python -m app.services.yasa_audit build <project> --out DIR     # stage 1 only
    python -m app.services.yasa_audit triage <project> --engine DIR --out DIR
    python -m app.services.yasa_audit trace <project> --out DIR     # mode A baseline (no engine)
    python -m app.services.yasa_audit authz <project> --out DIR [--product "public: /login, /search"]

LLM settings come from DeepAudit's LLM_BASE_URL / LLM_API_KEY / LLM_MODEL environment variables.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .config import AuditConfig
from .pipeline import authz, build, recon, trace, triage


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.services.yasa_audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "run", "build", "triage", "trace", "authz", "recon"):
        p = sub.add_parser(name)
        p.add_argument("project", type=Path)
        if name != "init":
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--deploy", default="",
                           help="deployment context, e.g. 'Linux container, Node 22'")
            p.add_argument("--workers", type=int, default=6)
            p.add_argument("--time-budget", type=float, default=30.0,
                           help="wall-clock budget in minutes (default 30); unreviewed candidates are listed")
        if name == "triage":
            p.add_argument("--engine", type=Path, required=True, help="output dir of the build stage")
        if name in ("authz", "recon"):
            p.add_argument("--product", default="",
                           help="product context, e.g. which routes are public by design and the roles")
        if name in ("run", "authz"):
            p.add_argument("--recon", action="store_true",
                           help="run the recon agent first (agent-authored routing recipe) and share its entries")
        if name in ("run", "triage"):
            p.add_argument("--group", choices=["file", "none"], default="file")
    args = ap.parse_args(argv)
    cfg = AuditConfig()
    root = args.project.resolve()

    if args.cmd == "init":
        r = subprocess.run([cfg.yasamcp_bin, "init", str(root), "--no-progress",
                            "-b", cfg.yasamcp_tools_dir])
        return r.returncode

    cfg.workers = args.workers
    cfg.time_budget_s = int(args.time_budget * 60)
    start = time.time()
    deadline = start + cfg.time_budget_s
    if args.cmd == "build":
        result = build(cfg, root, args.out, args.deploy, deadline)
    elif args.cmd == "triage":
        result = triage(cfg, root, args.engine, args.out, args.group, args.deploy, deadline)
    elif args.cmd == "recon":
        result = recon(cfg, root, args.out, args.deploy, args.product, deadline=deadline)
    elif args.cmd == "authz":
        ef = args.out / "recon" / "entries.json"
        if getattr(args, "recon", False):
            recon(cfg, root, args.out / "recon", args.deploy, args.product,
                  start + 0.3 * cfg.time_budget_s)
        result = authz(cfg, root, args.out, args.deploy, args.product, deadline=deadline,
                       entries_file=ef if ef.exists() else None)
    elif args.cmd == "trace":
        result = trace(cfg, root, args.out, args.deploy, deadline)
    else:
        ef = None
        rec = None
        if getattr(args, "recon", False):
            rec = recon(cfg, root, args.out / "recon", args.deploy, "", start + 0.2 * cfg.time_budget_s)
            ef = args.out / "recon" / "entries.json"
            ef = ef if ef.exists() else None
        build_deadline = start + cfg.build_share * cfg.time_budget_s
        b = build(cfg, root, args.out / "build", args.deploy, build_deadline, entries_file=ef)
        t = triage(cfg, root, args.out / "build", args.out / "triage", args.group, args.deploy, deadline)
        result = {"recon": rec, "build": b, "triage": t,
                  "total_tokens": b["prompt_tokens"] + b["completion_tokens"]
                  + t["prompt_tokens"] + t["completion_tokens"],
                  "total_wall_s": round(time.time() - start, 1),
                  "time_budget_s": cfg.time_budget_s}
        (args.out / "metrics.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
