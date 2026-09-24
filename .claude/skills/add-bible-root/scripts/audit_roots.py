#!/usr/bin/env python3
"""
Audit existing roots-in-bible files: regenerate every root the same way add_root.py does
(Dicta → app-aligned word indexes) and compare with what is committed. Read-only unless --apply.

Report categories per root:
  same         identical content
  index_fix    same verses, some word indexes differ (old index pointed at another word)
  verses_diff  Dicta (or the ס/שׂ split) gives a different set of verses
  unresolved   some Dicta hits could not be matched to the app text (listed)
  error        Dicta request failed / returned nothing

Every run also checks that each file in formatted/ and minified/ is UTF-16 BE with a BOM (the app
decodes them only that way) and lists the files that aren't. --encoding runs only this check.

Examples:
  audit_roots.py --out <dir>              # all roots → <dir>/report.json
  audit_roots.py --out <dir> --only ספר --only שפט
  audit_roots.py --out <dir> --apply index_fix   # rewrite whole files of that category (review first!)
  audit_roots.py --encoding                        # encoding check only (no Dicta), exit 1 on problems
"""

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

import add_root as ar

SWAP = {"ס": "שׂ", "ש": "ס"}


def rival_roots(root: str) -> list[str]:
    """ס/שׂ look-alikes of the root: a hit written with the other letter belongs to the other root."""
    plain = root.replace(ar.SHIN_DOT, "").replace(ar.SIN_DOT, "")
    out = []
    for i, ch in enumerate(plain):
        if ch in SWAP and not (ch == "ש" and ar.SHIN_DOT in root):
            out.append(plain[:i] + SWAP[ch] + plain[i + 1:])
    return out


def load(path: Path) -> dict:
    b = path.read_bytes()
    return json.loads((b[2:].decode("utf-16-be") if b[:2] == b"\xfe\xff" else b.decode("utf-8-sig")))


def encoding_problems(repo: Path) -> list[str]:
    """Root files that are not UTF-16 BE with a BOM (e.g. saved as UTF-8 by GitHub's web editor)."""
    problems = []
    for path in sorted([*repo.glob("formatted/*/*.json"), *repo.glob("minified/*/*.json")]):
        b = path.read_bytes()
        rel = path.relative_to(repo)
        if b[:2] != b"\xfe\xff":
            kind = "UTF-8 with BOM" if b[:3] == b"\xef\xbb\xbf" else \
                "UTF-16 LE" if b[:2] == b"\xff\xfe" else f"no UTF-16 BE BOM (starts {b[:4].hex(' ')})"
            problems.append(f"{rel}: {kind}")
            continue
        try:
            json.loads(b[2:].decode("utf-16-be"))
        except (UnicodeDecodeError, ValueError) as e:
            problems.append(f"{rel}: invalid UTF-16 BE JSON ({e})")
    return problems


def fetch_cached(query: str, cache: Path) -> str:
    f = cache / f"{query}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    for attempt in range(4):
        try:
            text = ar.fetch(query)
            f.write_text(text, encoding="utf-8")
            return text
        except Exception:  # noqa: BLE001 — retry transient network errors
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def audit(root: str, repo: Path, app: ar.AppText, cache: Path) -> dict:
    old = load(repo / "formatted" / root[0] / f"{root}.json")
    try:
        text = fetch_cached(ar.dicta_query(root), cache)
        hits = ar.parse(text) if "תנ\"ך/" in text else []
    except Exception as e:  # noqa: BLE001
        return {"root": root, "category": "error", "error": repr(e)}
    if not hits:
        return {"root": root, "category": "error", "error": "no Dicta results"}

    rivals = rival_roots(root)
    unresolved, moved, variants, to_rival = [], 0, 0, 0
    kept = []
    for h in hits:
        ar.align(h, app)
        if h.note.startswith("NOT FOUND"):
            unresolved.append(f"{h.ref} w={h.word_index} {h.word} ({h.note})")
            continue
        moved += h.note.startswith("moved")
        variants += h.note.startswith("app spells")
        if rivals and ar.classify(h.app_word or h.word, [root] + rivals) in rivals:
            to_rival += 1
            continue
        kept.append(h)

    new = ar.build(kept, old["root"])
    o = {(x["b"], x["c"], x["v"]): x["w"] for x in old["list"]}
    n = {(x["b"], x["c"], x["v"]): x["w"] for x in new["list"]}
    ref = lambda k: f"{ar.BOOKS[k[0]]} {k[1]}:{k[2]}"
    added = [f"{ref(k)} w={n[k]}" for k in n if k not in o]
    removed = [f"{ref(k)} w={o[k]}" for k in o if k not in n]
    changed = [f"{ref(k)} {o[k]}→{n[k]}" for k in o if k in n and o[k] != n[k]]

    if unresolved:
        category = "unresolved"
    elif added or removed:
        category = "verses_diff"
    elif changed or old != new:
        category = "index_fix"
    else:
        category = "same"
    return {
        "root": root, "category": category,
        "old": [old["total"], old["diff_verses"]], "new": [new["total"], new["diff_verses"]],
        "added": added, "removed": removed, "changed": changed, "unresolved": unresolved,
        "moved": moved, "variants": variants, "to_rival": to_rival, "new_data": new,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[4]))
    ap.add_argument("--app-chapters",
                    default=str(Path(__file__).resolve().parents[5] / "BibleContestAndroidApp/shared/src/"
                                "commonMain/moko-resources/assets/allChapters"))
    ap.add_argument("--out", help="directory for the report and the Dicta cache (required unless --encoding)")
    ap.add_argument("--only", action="append", help="audit only these roots")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--apply", action="append", default=[],
                    help="rewrite files of these categories from the last report (e.g. index_fix)")
    ap.add_argument("--encoding", action="store_true",
                    help="only check that every root file is UTF-16 BE with a BOM")
    args = ap.parse_args()

    repo = Path(args.repo)
    bad_encoding = encoding_problems(repo)
    for line in bad_encoding:
        print(f"ENCODING {line}", file=sys.stderr)
    if args.encoding:
        print(f"{len(bad_encoding)} file(s) not UTF-16 BE with BOM")
        sys.exit(1 if bad_encoding else 0)
    if not args.out:
        ap.error("--out is required")

    out = Path(args.out)
    cache = out / "dicta"
    cache.mkdir(parents=True, exist_ok=True)
    report_file = out / "report.json"

    if args.apply:
        report = json.loads(report_file.read_text(encoding="utf-8"))
        n = 0
        for r in report:
            if r["category"] in args.apply and (not args.only or r["root"] in args.only):
                data = r["new_data"]
                ar.write_utf16(repo / "formatted" / r["root"][0] / f"{r['root']}.json",
                               json.dumps(data, ensure_ascii=False, indent=2))
                ar.write_utf16(repo / "minified" / r["root"][0] / f"{r['root']}.json",
                               json.dumps(data, ensure_ascii=False, separators=(",", ":")))
                n += 1
        print(f"rewrote {n} root(s)")
        return

    app = ar.AppText(Path(args.app_chapters))
    roots = args.only or sorted(p.stem for p in (repo / "formatted").glob("*/*.json"))
    results = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(audit, r, repo, app, cache): r for r in roots}
        for i, f in enumerate(cf.as_completed(futures), 1):
            results.append(f.result())
            if i % 50 == 0:
                print(f"{i}/{len(roots)}", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["root"])
    report_file.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    summary: dict[str, int] = {}
    for r in results:
        summary[r["category"]] = summary.get(r["category"], 0) + 1
    if bad_encoding:
        summary["bad_encoding_files"] = len(bad_encoding)
    print(json.dumps(summary, ensure_ascii=False))
    print(f"report: {report_file}")


if __name__ == "__main__":
    main()
