#!/usr/bin/env python3
"""
Build roots-in-bible JSON files for one or more Hebrew roots from Dicta's Tanach search.

Fetches the Dicta search results (with nikud, so ס / שׂ / שׁ can be told apart), computes the
1-based word index of every highlighted word exactly the way the Bible Contest app splits a verse
(whitespace + makaf split, paseq attached to the previous word, Dicta's censored divine names kept
as one word), classifies each hit to one of the requested roots by the letters it is written with,
and writes formatted/<letter>/<root>.json + minified/<letter>/<root>.json (UTF-16 BE with BOM, no
trailing newline — the format of the existing files).

Dry run by default: prints a review table. Pass --write to create the files.

Examples:
  add_root.py --root זרר
  add_root.py --query ספק --root ספק --root שפק
  add_root.py --query ספק --root ספק --root שפק --assign "איוב:לו:יח=שפק" --write
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DICTA_URL = "https://tanach-search-3-0.loadbalancer.dicta.org.il/download"

# Same order as BibleCatalog.books in the app ("b" is the 0-based index into this list).
BOOKS = [
    "בראשית", "שמות", "ויקרא", "במדבר", "דברים", "יהושע", "שופטים", "שמואל א", "שמואל ב",
    "מלכים א", "מלכים ב", "ישעיהו", "ירמיהו", "יחזקאל", "הושע", "יואל", "עמוס", "עובדיה",
    "יונה", "מיכה", "נחום", "חבקוק", "צפניה", "חגי", "זכריה", "מלאכי", "תהילים", "משלי",
    "איוב", "שיר השירים", "רות", "איכה", "קהלת", "אסתר", "דניאל", "עזרא", "נחמיה",
    "דברי הימים א", "דברי הימים ב",
]

MAKAF = "־"
PASEQ = "׀"
SHIN_DOT = "ׁ"
SIN_DOT = "ׂ"
FINALS = str.maketrans("ךםןףץ", "כמנפצ")
GEMATRIA = {ch: v for ch, v in zip("אבגדהוזחטיכלמנסעפצקרשת",
                                   [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60, 70, 80, 90,
                                    100, 200, 300, 400])}
REF_RE = re.compile(r'^תנ"ך/[^/]+/ספר (?P<book>[^/]+)/פרק (?P<chapter>[^/]+)/פסוק (?P<verse>[^/]+)$')


def is_mark(ch: str) -> bool:
    """Nikud / te'amim combining mark (not makaf, paseq, sof pasuk or nun hafucha)."""
    return "֑" <= ch <= "ׇ" and ch not in (MAKAF, PASEQ, "׃", "׆")


def letters(s: str) -> str:
    return re.sub(r"[^א-ת]", "", s)


def gematria(s: str) -> int:
    return sum(GEMATRIA[ch] for ch in letters(s).translate(FINALS))


def dicta_query(root: str) -> str:
    """Dicta needs real spelling: final form for the last letter, no sin/shin dot (ספק, כסף)."""
    plain = root.replace(SHIN_DOT, "").replace(SIN_DOT, "")
    return plain[:-1] + plain[-1].translate(str.maketrans("כמנפצ", "ךםןףץ"))


def normalize_root(root: str) -> str:
    """Existing files never use final letters (כספ, סלמ); keep a sin/shin dot if given (שׂה)."""
    return root.translate(FINALS)


@dataclass
class Hit:
    book: int
    chapter: int
    verse: int
    word_index: int  # 1-based
    word: str  # with nikud, as shown by Dicta
    verse_text: str
    root: str | None = None
    note: str = ""
    app_word: str | None = None  # the same word in the app's own text, when checked

    @property
    def ref(self) -> str:
        return f"{BOOKS[self.book]} {self.chapter}:{self.verse}"


@dataclass
class Word:
    text: str = ""
    hit: bool = False


def split_verse(line: str) -> list[Word]:
    """
    Split a Dicta verse line (with *highlight* markers) into the app's words.

    - whitespace separates words; a real makaf also separates (the app splits "עַל־אֹדֹות" in two)
    - Dicta censors divine names by replacing one letter with a makaf ("אֱ־ֹהִים", "יְ־וָה",
      "צְ־ָאוֹת", "אֵ־"): such a makaf does not split. Detected when a nikud mark follows it, when
      nothing follows it inside the token, or when it is "…י־וה" (יהוה).
    - a paseq (׀) standing alone belongs to the previous word
    - ketiv/qere "(כתיב) [קְרִי]": only the qere is a word (the ketiv is dropped, brackets removed)
    """
    # Dicta sometimes highlights only the ketiv: "*(אלו)* [אֵלָיו]" → move the highlight to the qere
    line = re.sub(r"\*\([^)]*\)\*(\s*)\[([^\]]*)\]", r"\1*[\2]*", line)
    line = re.sub(r"\([^)]*\)", "", line).replace("[", "").replace("]", "")
    words: list[Word] = []
    cur = Word()
    inside = False

    def flush():
        nonlocal cur
        if letters(cur.text):
            words.append(cur)
        elif cur.text.strip() and words:  # paseq / stray punctuation → previous word
            words[-1].text += cur.text
            words[-1].hit |= cur.hit
        cur = Word()

    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "*":
            inside = not inside
        elif ch.isspace():
            flush()
        elif ch == MAKAF:
            cur.text += ch
            if inside:
                cur.hit = True
            rest = line[i + 1:]
            nxt = rest[:1]
            right = letters(re.split(r"[\s־]", rest.replace("*", ""), maxsplit=1)[0])
            censored = (
                not nxt or nxt.isspace() or is_mark(nxt)
                or (right == "וה" and letters(cur.text).endswith("י"))
            )
            if not censored:
                flush()
        else:
            cur.text += ch
            if inside:
                cur.hit = True
        i += 1
    flush()
    return words


def fetch(query: str) -> str:
    data = urllib.parse.urlencode({
        "downloadType": "TXT",
        "replaceShemos": "false",
        "showNikudAndTeamim": "BOTH",
        "sort": "corpus_order_path",
        "query": query,
    }).encode()
    req = urllib.request.Request(DICTA_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read().decode("utf-8-sig")


def parse(text: str) -> list[Hit]:
    hits: list[Hit] = []
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and ln != "Search Results"]
    i = 0
    while i < len(lines):
        m = REF_RE.match(lines[i])
        if not m:
            raise ValueError(f"Unexpected line in Dicta output: {lines[i]!r}")
        book = m["book"]
        if book not in BOOKS:
            raise ValueError(f"Unknown book name from Dicta: {book!r}")
        verse_line = lines[i + 1]
        words = split_verse(verse_line)
        found = [(n, w) for n, w in enumerate(words, 1) if w.hit]
        if not found:  # e.g. only a ketiv-without-qere was highlighted: not a word in the app
            print(f"warning: skipped, no countable highlighted word in {lines[i]}: {verse_line}",
                  file=sys.stderr)
        for n, w in found:
            hits.append(Hit(BOOKS.index(book), gematria(m["chapter"]), gematria(m["verse"]), n,
                            w.text, verse_line.replace("*", "")))
        i += 2
    return hits


def classify(word: str, roots: list[str]) -> str | None:
    """Pick the root whose distinguishing letters are the ones the word is written with."""
    if len(roots) == 1:
        return roots[0]
    # skeleton with the sin/shin dot kept on ש
    skel = []
    for idx, ch in enumerate(word):
        if "א" <= ch <= "ת":
            dot = ""
            j = idx + 1
            while j < len(word) and is_mark(word[j]):
                if word[j] in (SHIN_DOT, SIN_DOT):
                    dot = word[j]
                j += 1
            skel.append((ch.translate(FINALS), dot))

    def fits(root: str) -> bool:
        # root letters as (letter, required dot or "")
        req = []
        for ch in root:
            if ch in (SHIN_DOT, SIN_DOT):
                req[-1] = (req[-1][0], ch)
            else:
                req.append((ch, ""))
        pos = 0
        for letter, dot in req:  # subsequence match
            while pos < len(skel) and not (skel[pos][0] == letter and (not dot or skel[pos][1] == dot)):
                pos += 1
            if pos == len(skel):
                return False
            pos += 1
        return True

    candidates = [r for r in roots if fits(r)]
    return candidates[0] if len(candidates) == 1 else None


class AppText:
    """
    The Bible Contest app's own chapter text (moko-resources assets/allChapters, UTF-16), which is
    what the app highlights "w" against. Dicta uses a different edition: verse numbering can differ
    (Dicta ירמיהו לא:יט = app לא:יח) and a few words are spelled differently (איוב לד:לז
    יִסְפּוֹק vs יִשְׂפּוֹק), so every hit is checked — and if needed re-mapped — against it.
    """

    def __init__(self, directory: Path):
        self.dir = directory
        self.cache: dict[tuple[int, int], dict[int, list[str]]] = {}

    def chapter(self, book: int, chapter: int) -> dict[int, list[str]]:
        key = (book, chapter)
        if key not in self.cache:
            files = list(self.dir.glob(f"_{book + 1}_*-{chapter:0{3 if book == 26 else 2}d}.txt"))
            self.cache[key] = self._parse(files[0].read_bytes().decode("utf-16")) if files else {}
        return self.cache[key]

    @staticmethod
    def _parse(text: str) -> dict[int, list[str]]:
        text = re.sub(r"\{[^}]*\}", " ", text.split("\n", 1)[1])  # drop title line, {פ} {ס}...
        verses: dict[int, list[str]] = {}
        cur, expected = 0, 1
        for tok in text.split():
            marked = any(is_mark(ch) for ch in tok)
            # verse numbers are unpointed Hebrew numerals ("א", "יט") in sequence
            if not marked and re.fullmatch("[א-ת]{1,3}", tok) and gematria(tok) == expected:
                cur, expected = expected, expected + 1
                verses[cur] = []
                continue
            if not cur or tok == "\u05c6":
                continue  # before verse 1, or nun hafucha
            verses[cur].append(tok.replace("(", "").replace(")", ""))
        return {v: AppText._words(" ".join(t)) for v, t in verses.items()}

    @staticmethod
    def _words(verse: str) -> list[str]:
        out: list[str] = []
        for w in re.split(r"[\s\u05be]+", verse):
            if not w:
                continue
            if letters(w) and not any(is_mark(ch) for ch in w):
                continue  # unpointed ketiv, also after a makaf ("אֶת־החצי (הַחִצִּים)"): the app counts the qere
            if not letters(w) and out:  # paseq etc. belongs to the previous word
                out[-1] += w
            else:
                out.append(w)
        return out

    def word(self, book: int, chapter: int, verse: int, index: int) -> str | None:
        words = self.chapter(book, chapter).get(verse, [])
        return words[index - 1] if 0 < index <= len(words) else None


def same_word(a: str | None, b: str) -> bool:
    return a is not None and letters(a).translate(FINALS) == letters(b).translate(FINALS)


def align(h: Hit, app: AppText):
    """Match a Dicta hit to the app's text; fix verse/word numbering or flag a spelling variant."""
    if same_word(app.word(h.book, h.chapter, h.verse, h.word_index), h.word):
        h.app_word = app.word(h.book, h.chapter, h.verse, h.word_index)
        return
    # same word elsewhere nearby (other versification, or a different word count)
    candidates = []
    chapter = app.chapter(h.book, h.chapter)
    for v in range(h.verse - 3, h.verse + 4):
        for i, w in enumerate(chapter.get(v, []), 1):
            if same_word(w, h.word):
                candidates.append((abs(v - h.verse), abs(i - h.word_index), v, i, w))
    if candidates:
        candidates.sort()
        if len(candidates) == 1 or candidates[0][:2] != candidates[1][:2]:
            _, _, v, i, w = candidates[0]
            h.note = f"moved from {h.chapter}:{h.verse} w={h.word_index} to match the app text"
            h.verse, h.word_index, h.app_word = v, i, w
            return
    # same position, different spelling in the app's edition → keep the position, use the app's word
    w = app.word(h.book, h.chapter, h.verse, h.word_index)
    plene = lambda x: re.sub("[וי]", "", letters(x).translate(FINALS))  # ktiv male / haser
    if w and (plene(w) == plene(h.word) or (len(letters(w)) == len(letters(h.word)) and sum(
            x != y for x, y in zip(letters(w), letters(h.word))) == 1)):
        h.app_word = w
        h.note = f"app spells it {w} (Dicta: {h.word})"
        return
    h.note = f"NOT FOUND in app text (app w={h.word_index}: {w})"


def build(hits: list[Hit], root: str) -> dict:
    by_verse: dict[tuple[int, int, int], list[int]] = {}
    for h in sorted(hits, key=lambda h: (h.book, h.chapter, h.verse, h.word_index)):
        words = by_verse.setdefault((h.book, h.chapter, h.verse), [])
        if h.word_index not in words:  # two Dicta hits can land on the same app word
            words.append(h.word_index)
    return {
        "total": sum(len(w) for w in by_verse.values()),
        "root": root,
        "diff_verses": len(by_verse),
        "list": [{"b": b, "c": c, "v": v, "w": w} for (b, c, v), w in by_verse.items()],
    }


def write_utf16(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))


def parse_assign(spec: str) -> tuple[tuple[int, int, int, int | None], str]:
    """'איוב:לו:יח=שפק' or 'איוב:לו:יח:3=שפק' (3 = word index); target '-' drops the hit."""
    ref, target = spec.rsplit("=", 1)
    parts = ref.split(":")
    if parts[0] not in BOOKS:
        raise SystemExit(f"--assign: unknown book {parts[0]!r}")
    word = int(parts[3]) if len(parts) > 3 else None

    def num(s: str) -> int:
        return int(s) if s.isdigit() else gematria(s)

    return (BOOKS.index(parts[0]), num(parts[1]), num(parts[2]), word), target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", required=True,
                    help="root to create (repeat for a ס/שׂ-style split); e.g. ספק, שׂה")
    ap.add_argument("--query", action="append",
                    help="Dicta query (repeatable, results are merged); default: each --root")
    ap.add_argument("--assign", action="append", default=[],
                    help="override: 'ספר:פרק:פסוק[:מילה]=שורש' (or =- to drop the hit)")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[4]),
                    help="roots-in-bible checkout (default: the repo this script lives in)")
    ap.add_argument("--app-chapters",
                    default=str(Path(__file__).resolve().parents[5] / "BibleContestAndroidApp/shared/src/"
                                "commonMain/moko-resources/assets/allChapters"),
                    help="the app's allChapters assets, to check/fix every hit against the app text")
    ap.add_argument("--input", action="append", help="use saved Dicta TXT files instead of fetching")
    ap.add_argument("--write", action="store_true", help="write the JSON files (default: dry run)")
    ap.add_argument("--force", action="store_true", help="overwrite existing root files")
    args = ap.parse_args()

    roots = [normalize_root(r) for r in args.root]
    texts = ([Path(p).read_text(encoding="utf-8-sig") for p in args.input] if args.input
             else [fetch(q) for q in (args.query or [dicta_query(r) for r in args.root])])

    merged: dict[tuple[int, int, int, int], Hit] = {}
    for text in texts:
        for h in parse(text):
            merged.setdefault((h.book, h.chapter, h.verse, h.word_index), h)
    hits = list(merged.values())

    app_dir = Path(args.app_chapters)
    if app_dir.is_dir():
        app = AppText(app_dir)
        for h in hits:
            align(h, app)
    else:
        print(f"warning: {app_dir} not found — hits NOT checked against the app text", file=sys.stderr)

    overrides = dict(parse_assign(s) for s in args.assign)
    for target in overrides.values():
        if target != "-" and normalize_root(target) not in roots:
            raise SystemExit(f"--assign target {target!r} is not one of --root {roots}")

    used = set()
    for h in hits:
        for key in ((h.book, h.chapter, h.verse, h.word_index), (h.book, h.chapter, h.verse, None)):
            if key in overrides:
                used.add(key)
                h.root = None if overrides[key] == "-" else normalize_root(overrides[key])
                h.note = "assigned" if h.root else "dropped"
                break
        else:
            if h.note.startswith("NOT FOUND"):
                continue
            h.root = classify(h.app_word or h.word, roots)
            if h.root is None:
                h.note = (h.note + "; " if h.note else "") + "UNRESOLVED"
    for key in set(overrides) - used:
        print(f"warning: --assign {key} matched no hit", file=sys.stderr)

    hits.sort(key=lambda h: (h.book, h.chapter, h.verse, h.word_index))
    print(f"{len(hits)} hits from Dicta\n")
    for h in hits:
        print(f"{h.ref:<20} w={h.word_index:<3} {h.app_word or h.word:<22} → {h.root or '-':<5} {h.note}")
    print()

    unresolved = [h for h in hits if h.root is None and h.note != "dropped"]
    if unresolved:
        print(f"{len(unresolved)} hit(s) unresolved (not found in the app text, or no single root "
              "fits); resolve with --assign "
              "'ספר:פרק:פסוק[:מילה]=שורש' (or =-)", file=sys.stderr)
        sys.exit(2)

    repo = Path(args.repo)
    outputs = []
    for root in roots:
        data = build([h for h in hits if h.root == root], root)
        letter = root[0]
        outputs.append((root, data, repo / "formatted" / letter / f"{root}.json",
                        repo / "minified" / letter / f"{root}.json"))
        print(f"{root}: total={data['total']} diff_verses={data['diff_verses']}")
        print("  " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    if not args.write:
        print("\nDry run — pass --write to create the files.")
        return
    for root, data, formatted, minified in outputs:
        if data["total"] == 0:
            print(f"skip {root}: no occurrences", file=sys.stderr)
            continue
        for p in (formatted, minified):
            if p.exists() and not args.force:
                raise SystemExit(f"{p} already exists (use --force to overwrite)")
        write_utf16(formatted, json.dumps(data, ensure_ascii=False, indent=2))
        write_utf16(minified, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"wrote {formatted.relative_to(repo)} and {minified.relative_to(repo)}")
    update_index(repo)


def update_index(repo: Path):
    """Rewrite roots-index.json (the site's list of roots) with the Kotlin tool."""
    result = subprocess.run([str(repo / "gradlew"), "-q", ":tools:run", "--args=index"], cwd=repo)
    if result.returncode != 0:
        print("warning: roots-index.json was NOT updated; run ./gradlew -q :tools:run --args=index",
              file=sys.stderr)


if __name__ == "__main__":
    main()
