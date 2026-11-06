"""Score findings against the benchmark ground truth (data-flow scope).

    python benchmarks/yasa_audit/eval.py --project juice-mini OUT/triage/findings.json [more.json ...]

A finding matches a ground-truth item when its sink file matches, its sink line is within the item's
line range +-3, and its CWE is in the same family. Negatives are look-dangerous-but-safe sites.
Items marked "added" were reported by a tool first and then verified by hand (see groundtruth/*.yaml).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GT: dict[str, dict] = {
    "hms": {
        "pos": [
            ("HMS-01", "src/com/hospdbms/pkg/Plogin.java", 51, 53, "CWE-89"),
            ("HMS-02", "src/com/hospdbms/pkg/Doclogin.java", 51, 53, "CWE-89"),
            ("HMS-03", "WebContent/delptnt.jsp", 16, 20, "CWE-89"),
            ("HMS-04", "WebContent/success.jsp", 25, 25, "CWE-89"),
            ("HMS-05", "WebContent/successbapn.jsp", 20, 20, "CWE-89"),
            ("HMS-06", "WebContent/successupdate.jsp", 27, 27, "CWE-89"),
            ("HMS-07", "WebContent/successupdate.jsp", 29, 29, "CWE-89"),
            ("HMS-08", "WebContent/updateprofile.jsp", 51, 53, "CWE-89"),
            ("HMS-09", "WebContent/apn-his.jsp", 54, 105, "CWE-89"),
            ("HMS-17", "WebContent/mangptnts.jsp", 102, 110, "CWE-79"),
            ("HMS-18", "WebContent/viewptnts.jsp", 58, 65, "CWE-79"),
            ("HMS-19", "WebContent/apn-his.jsp", 112, 116, "CWE-79"),
            ("HMS-24", "WebContent/updateprofile.jsp", 40, 157, "CWE-79"),  # added
        ],
        "neg": [
            ("HMS-N01", "WebContent/include/header.php", 35, 35),
            ("HMS-N02", "WebContent/adminpage.jsp", 39, 40),
            ("HMS-N03", "WebContent/apn-his.jsp", 46, 46),
            ("HMS-N04", "WebContent/mngdoc.jsp", 87, 94),
        ],
        "ambiguous": [],
    },
    "juice": {
        "pos": [
            ("JS-login", "routes/login.ts", 34, 34, "CWE-89"),
            ("JS-search", "routes/search.ts", 23, 23, "CWE-89"),
            ("JS-noSqlReviews", "routes/updateProductReviews.ts", 16, 20, "CWE-943"),
            ("JS-redirect", "routes/redirect.ts", 15, 18, "CWE-601"),
            ("JS-E01", "routes/trackOrder.ts", 15, 18, "CWE-943"),
            ("JS-E02", "routes/showProductReviews.ts", 36, 36, "CWE-943"),
            ("JS-E03", "routes/b2bOrder.ts", 21, 23, "CWE-94"),
            ("JS-E04", "routes/userProfile.ts", 60, 65, "CWE-94"),
            ("JS-E05", "routes/userProfile.ts", 73, 90, "CWE-1336"),
            ("JS-E06", "routes/fileUpload.ts", 80, 80, "CWE-611"),
            ("JS-E07", "routes/fileUpload.ts", 114, 114, "CWE-776"),
            ("JS-E08", "routes/profileImageUrlUpload.ts", 20, 24, "CWE-918"),
            ("JS-E09", "routes/dataErasure.ts", 103, 107, "CWE-22"),
            ("JS-E10", "routes/fileServer.ts", 26, 32, "CWE-22"),
            ("JS-E11", "routes/fileUpload.ts", 29, 34, "CWE-22"),  # added
            ("JS-E12", "routes/trackOrder.ts", 15, 24, "CWE-79"),  # added
            ("JS-E13", "routes/likeProductReviews.ts", 25, 52, "CWE-943"),  # added
        ],
        "neg": [
            ("JS-N01", "routes/captcha.ts", 22, 22),
            ("JS-N02", "routes/keyServer.ts", 12, 14),
            ("JS-N03", "routes/logfileServer.ts", 12, 14),
            ("JS-N04", "server.ts", 140, 140),
            ("JS-N05", "routes/quarantineServer.ts", 12, 14),
            ("JS-N06", "routes/chat.ts", 147, 150),  # Number(id) before $where
        ],
        "ambiguous": [("routes/vulnCodeFixes.ts", 1, 200)],
    },
}
GT["juice-mini"] = {"pos": GT["juice"]["pos"],
                    "neg": [n for n in GT["juice"]["neg"] if n[0] not in ("JS-N04", "JS-N06")],
                    "ambiguous": GT["juice"]["ambiguous"]}
ALIASES = {"JS-redirect": [("lib/insecurity.ts", 120, 140)], "JS-E06": [("lib/xml.ts", 33, 40)]}
FAMILIES = [{"CWE-89", "CWE-943"}, {"CWE-94", "CWE-95", "CWE-1336", "CWE-78"},
            {"CWE-22", "CWE-73", "CWE-158", "CWE-23"}, {"CWE-611", "CWE-776", "CWE-827"},
            {"CWE-776", "CWE-400", "CWE-502"}]
SLACK = 3


def norm(p: str | None) -> str:
    return (p or "").replace("\\", "/").lstrip("./").lstrip("/")


def hit(f_file: str | None, f_line: int | None, g_file: str, lo: int, hi: int) -> bool:
    a, b = norm(f_file), norm(g_file)
    same = a == b or a.endswith("/" + b) or b.endswith("/" + a)
    return same and lo - SLACK <= int(f_line or 0) <= hi + SLACK


def cwe_ok(f_cwe: str | None, g_cwe: str) -> bool:
    a = (f_cwe or "").upper().replace(" ", "")
    return not a or a == g_cwe or any(a in s and g_cwe in s for s in FAMILIES)


def score(project: str, findings: list[dict]) -> dict:
    gt = GT[project]
    reported = [f for f in findings if f.get("verdict") in ("confirmed", "likely")]
    rejected = [f for f in findings if f.get("verdict") == "false_positive"]

    def match_pos(f: dict) -> list[str]:
        out = []
        for gid, gf, lo, hi, g_cwe in gt["pos"]:
            locs = [(gf, lo, hi)] + ALIASES.get(gid, [])
            if any(hit(f.get("sink_file"), f.get("sink_line"), *loc) for loc in locs) and cwe_ok(
                    f.get("cwe"), g_cwe):
                out.append(gid)
        return out

    found: set[str] = set()
    unmatched, neg_hits = [], []
    for f in reported:
        ids = match_pos(f)
        found.update(ids)
        loc = f"{norm(f.get('sink_file'))}:{f.get('sink_line')}"
        if ids or any(hit(f.get("sink_file"), f.get("sink_line"), *a) for a in gt["ambiguous"]):
            continue
        n = [nid for nid, nf, lo, hi in gt["neg"] if hit(f.get("sink_file"), f.get("sink_line"), nf, lo, hi)]
        (neg_hits if n else unmatched).append({"id": n[0] if n else "", "at": loc, "cwe": f.get("cwe")})
    return {
        "recall": f"{len(found)}/{len(gt['pos'])}",
        "reported": len(reported), "rejected": len(rejected),
        "negative_hits": neg_hits, "unmatched": unmatched,
        "missed": sorted({g[0] for g in gt["pos"]} - found),
        "wrongly_rejected": sorted({g for f in rejected for g in match_pos(f)} - found),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, choices=sorted(GT))
    ap.add_argument("findings", nargs="+", type=Path)
    args = ap.parse_args()
    for path in args.findings:
        data = json.loads(path.read_text())
        print(path, json.dumps(score(args.project, data.get("findings", [])), ensure_ascii=False))


if __name__ == "__main__":
    main()
