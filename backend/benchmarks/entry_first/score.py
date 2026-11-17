"""Score an entry-first run against a label file, so method changes are judged on recall, false
positives and cost rather than on one reading of one run.

    python score.py <labels.json> <run_dir> [run_dir ...]

For a CVE label file, each advisory is scored on two things, independently:
- reached: recon enumerated an entry whose handler file (or handler/route) matches the advisory;
- found: a kept finding points at one of the advisory's files (and, when given, functions).
A CVE can be reached-but-not-found (reviewed, missed) or not-reached (recon gap) — the distinction
is what tells recon problems from review problems.

For the Ghost root-cause file, each labelled root cause is matched to the run's refutation verdict,
so the refutation check is scored against the hand-verified true/false split.

Several run_dirs are summarised together (mean and the per-run spread), because a single run's
numbers move more than most method changes do.
"""
import json
import re
import sys
from pathlib import Path


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def _route_key(route: str) -> str:
    return _norm(re.sub(r":[a-z_]+|\{[^}]+\}|\*", "", str(route).lower()))


def _entries(run: Path) -> list[dict]:
    f = run / "recon" / "entries.json"
    return json.loads(f.read_text()) if f.exists() else []


def _findings(run: Path) -> dict:
    f = run / "review" / "findings.json"
    return json.loads(f.read_text()) if f.exists() else {"findings": [], "refuted": []}


def _reached(adv: dict, entries: list[dict]) -> bool:
    files = {_norm(x) for x in adv.get("files", [])}
    ent = adv.get("entry", {})
    want_routes = [_route_key(r) for r in ent.get("routes", [])]
    want_handlers = [_norm(h) for h in ent.get("handlers", [])]
    for e in entries:
        hf = _norm(e.get("handler_file"))
        if any(f and f in hf for f in files):
            return True
        rk = _route_key(e.get("route", ""))
        if any(w and w in rk for w in want_routes):
            return True
        h = _norm(e.get("handler")) + _norm(e.get("handler_file"))
        if any(w and w in h for w in want_handlers):
            return True
    return False


def _found(adv: dict, findings: list[dict]) -> dict | None:
    files = {_norm(x) for x in adv.get("files", [])}
    funcs = {_norm(x) for x in adv.get("functions", [])}
    for fd in findings:
        blob = _norm(fd.get("sink_file")) + _norm(fd.get("handler")) + _norm(json.dumps(fd.get("route_evidence")))
        if not any(f and f in blob for f in files):
            continue
        if funcs:
            fblob = blob + _norm(fd.get("root_cause")) + _norm(fd.get("entry"))
            if not any(fn and fn in fblob for fn in funcs):
                continue
        return fd
    return None


def score_cve(label: dict, runs: list[Path]) -> None:
    print(f"\n=== {label['project']} {label['ref']} — {len(label['advisories'])} advisories, {len(runs)} run(s)")
    # reached is scored over every run; found only over runs that produced a review (a recon-only run
    # cannot find anything, and would otherwise drag the found-rate down).
    per_adv: dict[str, list[bool]] = {a["id"]: [] for a in label["advisories"]}
    found_adv: dict[str, list[bool]] = {a["id"]: [] for a in label["advisories"]}
    for run in runs:
        entries, data = _entries(run), _findings(run)
        reviewed = bool(data.get("findings") or data.get("refuted") or (run / "review").exists()
                        and any((run / "review").glob("unit-*")))
        kept = [f for f in data.get("findings", []) if (f.get("verification") or {}).get("verdict") != "refuted"]
        for adv in label["advisories"]:
            reached = _reached(adv, entries)
            per_adv[adv["id"]].append(reached)
            if reviewed:
                found_adv[adv["id"]].append(bool(_found(adv, kept)) if reached else False)
    kinds: dict[str, list[int]] = {}
    for adv in label["advisories"]:
        rr, rn = sum(per_adv[adv["id"]]), len(per_adv[adv["id"]])
        ff, fn = sum(found_adv[adv["id"]]), len(found_adv[adv["id"]])
        ok = fn and ff == fn
        tag = "FOUND" if ok else "found(some)" if ff else ("reached, MISSED" if rr else "NOT REACHED")
        print(f"  {adv['id']:16} {adv.get('kind',''):9} reached {rr}/{rn}  found {ff}/{fn}  {tag}  — "
              f"{adv['title'][:58]}")
        kinds.setdefault(adv.get("kind", "?"), []).append(1 if ok else 0)
    reached_any = sum(any(per_adv[a["id"]]) for a in label["advisories"])
    found_all = sum(found_adv[a["id"]] and all(found_adv[a["id"]]) for a in label["advisories"])
    print(f"  reached by recon: {reached_any}/{len(label['advisories'])};  found (every reviewing run): "
          f"{found_all}/{len(label['advisories'])}")
    print("  found by kind: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(kinds.items())))


def score_ghost(label: dict, runs: list[Path]) -> None:
    print(f"\n=== {label['project']} {label['ref']} — refutation check vs {len(label['root_causes'])} "
          f"hand-verified root causes, {len(runs)} run(s)")
    want = {rc["id"]: rc["verdict"] for rc in label["root_causes"]}
    # confusion: for real root causes the check should uphold; for false_positive/non_finding it should refute
    agg = {"should_keep_kept": 0, "should_keep_dropped": 0, "should_drop_refuted": 0, "should_drop_kept": 0,
           "n": 0}
    for run in runs:
        data = _findings(run)
        verd: dict[str, str] = {}
        for f in data.get("findings", []) + data.get("refuted", []):
            iid = f.get("issue")
            v = (f.get("verification") or {}).get("verdict")
            if iid in want and v:
                verd[iid] = "refuted" if v == "refuted" else "kept"
        if not verd:
            continue
        agg["n"] += 1
        for iid, truth in want.items():
            got = verd.get(iid)
            if got is None:
                continue
            if truth == "real":
                agg["should_keep_kept" if got == "kept" else "should_keep_dropped"] += 1
            elif truth in ("false_positive", "non_finding"):
                agg["should_drop_refuted" if got == "refuted" else "should_drop_kept"] += 1
    print(f"  real kept {agg['should_keep_kept']}, real wrongly dropped {agg['should_keep_dropped']}")
    print(f"  false/non refuted {agg['should_drop_refuted']}, false/non wrongly kept {agg['should_drop_kept']}")
    tp, fn = agg["should_drop_refuted"], agg["should_drop_kept"]
    print(f"  refutation recall of bad findings: {tp}/{tp + fn}" if tp + fn else "  (no bad findings matched)")


def main() -> int:
    label = json.loads(Path(sys.argv[1]).read_text())
    runs = [Path(p) for p in sys.argv[2:]] or [Path(sys.argv[1]).parent]
    (score_ghost if "root_causes" in label else score_cve)(label, runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
