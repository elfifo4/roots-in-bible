---
name: add-bible-root
description: Add a new Hebrew root (שורש) to the roots-in-bible repo — fetch its occurrences from Dicta's Tanach search, compute the word indexes the Bible Contest app highlights, and write formatted/ + minified/ JSON files. Use whenever the user asks to add/create/generate a root, "הוסף שורש", "תוסיף את השורש X", "צור קובץ לשורש", or to split one Dicta search into several roots by letter (ס / שׂ, e.g. ספק + שפק). Also use to regenerate/fix an existing root file.
---

# Add a root to roots-in-bible

Each root lives in two files, `formatted/<first letter>/<root>.json` (indent 2) and
`minified/<first letter>/<root>.json` (compact). The Bible Contest app loads
`https://raw.githubusercontent.com/elfifo4/roots-in-bible/master/minified/<letter>/<root>.json`
for whatever the user types, so the app needs no list of roots. The GitHub Pages site
(`index.html`) does: it reads `roots-index.json` (root → letter folder, total, diff_verses).
**Every add, regenerate or fix of a root must update that index** — `add_root.py --write` does it
for you (see below).

```json
{"total":7,"root":"ספק","diff_verses":7,"list":[{"b":3,"c":24,"v":10,"w":[6]}, ...]}
```

- `b`: 0-based book index in the app's order (בראשית=0 … דברי הימים ב=38). `c`/`v`: chapter and verse, 1-based.
  `w`: 1-based indexes of the words in the verse **as the app splits it**.
- `total` is the total number of words (sum of all `w`). `diff_verses` is the number of verses.
- Encoding is **UTF-16 BE with a BOM** and no trailing newline. Key order is total, root, diff_verses, list.
- File names never use final letters (`כספ.json`, `סלמ.json`). A sin/shin dot is kept only to
  prevent a name clash (`שׂה.json`).

The script handles all of this. **Don't write these files by hand.**

## The script

`.claude/skills/add-bible-root/scripts/add_root.py` (Python 3, stdlib only). It runs as a dry run
unless you pass `--write`.

```bash
# one root
python3 .claude/skills/add-bible-root/scripts/add_root.py --root זרר
# one Dicta search split into several roots by the letter each word is written with
python3 .claude/skills/add-bible-root/scripts/add_root.py --root ספק --root שפק --query ספק --query שפק
# then add --write (and --force to overwrite existing files)
```

What it does:
1. POSTs to Dicta's download endpoint (`tanach-search-3-0.loadbalancer.dicta.org.il/download`,
   TXT, with nikud and te'amim). The default query is each `--root` with a final letter (`כסף`).
   A query without the final letter returns nothing. Results from several `--query` are merged.
2. Splits each verse the way the app does. Whitespace and makaf both separate words. A paseq
   joins the word before it. For ketiv/qere, only the qere counts. Dicta hides divine names by
   replacing a letter with a makaf (`יְ־וָה`, `אֱ־ֹהִים`, `צְ־ָאוֹת`), and those stay one word.
3. **Checks every hit against the app's own text**, the UTF-16 files in
   `../BibleContestAndroidApp/shared/src/commonMain/moko-resources/assets/allChapters`
   (override the path with `--app-chapters`). Dicta uses a different edition:
   - Verse numbering sometimes differs. Dicta's ירמיהו לא:יט is the app's לא:יח. The script
     moves the hit and notes `moved from …`.
   - Some words are spelled differently. Dicta has איוב לד:לז יִסְפּוֹק where the app has
     יִשְׂפּוֹק, and there are plene/defective pairs like דבריך/דברך. The script keeps the
     position, uses the app's word, and notes `app spells it …`.
   - Anything it can't match is marked `NOT FOUND` and blocks writing.
4. When more than one `--root` is given, it classifies each hit by the letters of the **app's**
   word. A root given with a sin/shin dot (e.g. `שׂפק`) only matches words with that dot.
5. Prints a review table and the JSON for each root. With `--write` it writes the files and then
   rewrites `roots-index.json` by running `./gradlew -q :tools:run --args=index` (Kotlin, in `tools/`).

## Workflow

1. Dry run and **show the user the review table**, especially rows with a note.
2. If the script exits with code 2, some hits are unresolved: not found in the app text, or no
   single root fits. Look at the verse and ask the user if the answer isn't obvious, then resolve
   it with `--assign`:
   - `--assign "שמות:כ:יז=אמר"`: set the root for every hit in that verse (Hebrew or digit numerals).
   - `--assign "שמות:כ:יז:1=אמר"`: set the root for word 1 only.
   - `--assign "שמות:כ:יז=-"`: drop the hit.

   Overrides use the verse and word numbers after the move to the app's text, as printed in the
   table.
3. Things that are the user's call. Ask them, don't guess:
   - a word written with one letter that Dicta attributes to the other root (בְסָפֶק, איוב לו:יח,
     comes back for the query `שפק`, but it's written with ס; the user chose the written letter
     in that case)
   - Dicta and the app disagreeing on the letter (for איוב לד:לז the user chose the app's
     spelling, which is the script's default)
   - words Dicta returns that don't belong to the root at all (Dicta does morphological search,
     so homographs slip in); drop them with `=-`
4. Run it again with `--write`. Check the result with `git status`: two new files per root, and
   `roots-index.json` changed. If the script warned that the index was not updated, run
   `./gradlew -q :tools:run --args=index` yourself. Then run
   `./gradlew -q :tools:run --args="check <root> ..."`: every verse must exist in `text/`, every
   word index must be in range, and the root's line in the index must be current.
5. Commit and push to `master` only if the user asked. The commit message follows the repo's
   style: `הוספת שורש ס-פ-ק` (for several roots: `הוספת שורשים ס-פ-ק, ש-פ-ק`). Stage only the
   root files, `roots-index.json` and the skill. `.idea/` changes are never part of it.

## Auditing existing files

`scripts/audit_roots.py --out <dir>` regenerates every committed root (or `--only X`) and compares
it to the file. It is read-only. It caches Dicta responses in `<dir>/dicta`, so a re-run is fast,
and writes `<dir>/report.json` with a category per root: `same`, `index_fix`, `verses_diff`,
`unresolved`, or `error`.

**Never rewrite verse sets from an audit.** Many file names are not the query that built them.
`אנש` holds 3,025 occurrences, and Dicta returns 76 for "אנש". `הימ`, `אבה`, `שׂה` and `שכל` were
built the same way, with a different query or deliberate curation. Only these changes are safe:
a verse that is in both versions, has the same number of words, and where each old index points
at a neighboring word (≤3 away) that is not one of the Dicta hit words. Then apply only those
index changes and keep everything else in the file. The first full audit (2026-09-23) fixed
98 such verses in 72 roots. They came from ketiv/qere, Ha'azinu's layout, the Ten Commandments'
numbering, and ketiv joined by a makaf (`אֶת־החצי (הַחִצִּים)`).

After changing any root file by hand or from an audit, run `./gradlew -q :tools:run --args=index`
(total / diff_verses may have changed) and commit `roots-index.json` with it.

## Validation reference

Regenerating existing roots with this script (אמר, דבר, ספר, שפט: about 9,600 hits) matched the
app's text for all but 3 hits (שמות כ:יז, ירמיהו לא:לה, תהילים קלט:כ), all real edition
differences that get flagged. Dicta returns more verses than some older files contain, because
the older files were generated differently. So if you regenerate an existing root, diff the
result against the old file and review the differences with the user before `--force`.

## The site and `text/`

`index.html` (GitHub Pages) shows a root's verses with its words highlighted. It loads
`roots-index.json`, the root file, and `text/<b>.json` for each book the root appears in: an array
of chapters, each an array of verse strings, exactly as the app shows them (ketiv replaced by
qere, `{פ}`/`{ס}` removed, NBSP before a paseq). `text/` is exported from the app's `allChapters`
and does not change when a root is added.

Word numbering on the site, in `tools/` and in `AppText._words` is the same: split on whitespace
(NBSP included) and makaf; a token with no Hebrew letter (a paseq, or the NBSP gap between the
halves of a verse in תהילים/משלי/איוב) belongs to the previous word.

`./gradlew -q :tools:run --args=check` checks all roots. Known problems as of 2026-09-24 (not
fixed): the Ten Commandments (שמות כ, דברים ה) use a different verse division than the app's
text; 4 off-by-one indexes (איוב יח:טו, זכריה יב:יא, ירמיהו נא:ג, שמואל א כד:ח); פצצ has
total/diff_verses 4 for a list of 3; `שׂה` and `שׂק` hold the same list.
