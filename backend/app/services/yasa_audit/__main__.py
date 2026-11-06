"""Command line entry point.

    python -m app.services.yasa_audit init  <project>               # build the yasa-mcp navigation cache
    python -m app.services.yasa_audit run   <project> --out DIR     # build rules + engine, then triage
    python -m app.services.yasa_audit build <project> --out DIR     # stage 1 only
    python -m app.services.yasa_audit triage <project> --engine DIR --out DIR
    python -m app.services.yasa_audit trace <project> --out DIR     # mode A baseline (no engine)

LLM settings come from DeepAudit's LLM_BASE_URL / LLM_API_KEY / LLM_MODEL environment variables.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import AuditConfig
from .pipeline import build, trace, triage


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.services.yasa_audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "run", "build", "triage", "trace"):
        p = sub.add_parser(name)
        p.add_argument("project", type=Path)
        if name != "init":
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--deploy", default="",
                           help="deployment context, e.g. 'Linux container, Node 22'")
            p.add_argument("--workers", type=int, default=3)
        if name == "triage":
            p.add_argument("--engine", type=Path, required=True, help="output dir of the build stage")
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
    if args.cmd == "build":
        result = build(cfg, root, args.out, args.deploy)
    elif args.cmd == "triage":
        result = triage(cfg, root, args.engine, args.out, args.group, args.deploy)
    elif args.cmd == "trace":
        result = trace(cfg, root, args.out, args.deploy)
    else:
        b = build(cfg, root, args.out / "build", args.deploy)
        t = triage(cfg, root, args.out / "build", args.out / "triage", args.group, args.deploy)
        result = {"build": b, "triage": t,
                  "total_tokens": b["prompt_tokens"] + b["completion_tokens"]
                  + t["prompt_tokens"] + t["completion_tokens"],
                  "total_wall_s": round(b["wall_s"] + t["wall_s"], 1)}
        (args.out / "metrics.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
