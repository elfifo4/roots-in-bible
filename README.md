# roots-in-bible

## Description

https://elfifo4.github.io/roots-in-bible/

This repository contains json files of all the roots (Shorashim שורשים) in the Bible and their occurrences within the verses.  
If you find any mistake, please open up a new issue.<br/>
Thanks

## Structure

```
minified/{first letter}/{root}.json   a root's occurrences (the app loads these)
formatted/{first letter}/{root}.json  the same, indented
roots-index.json                      every root: its folder letter, total and diff_verses
text/{b}.json                         the verse text of book b, as the app shows it (for the site)
index.html, fonts/                    the GitHub Pages site
tools/                                Kotlin: rebuilds roots-index.json and checks every root against text/
```

```json
{"total":7,"root":"ספק","diff_verses":7,"list":[{"b":3,"c":24,"v":10,"w":[6]}, …]}
```

- `b` – book index, **0-based** in the order of the Hebrew Bible (0 = Genesis … 38 = 2 Chronicles)
- `c`, `v` – chapter and verse, 1-based
- `w` – 1-based indexes of the root's words in the verse. The verse text has the qri in place of
  the ktiv. Words are separated by whitespace and maqaf; a paseq belongs to the word before it.
- `total` – number of words, `diff_verses` – number of different verses
- Root files are UTF-16 BE with a BOM. File names never use final letters (`כספ.json`).

After adding or changing a root, run `./gradlew -q :tools:run --args=index` and commit
`roots-index.json` with it. `./gradlew -q :tools:run --args=check` checks every root against `text/`.


## License

```
Copyright 2019 Elad Finish

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
