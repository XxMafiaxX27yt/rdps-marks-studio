# RDPS Marks Studio

A website for **Rukmini Devi Public School, Delhi** that turns a file of student marks into one complete,
beautiful Excel report, with dashboards, report cards, analysis, real Excel charts and a validation report.
You can also ask questions about the marks in plain English or Hinglish, typed or spoken, and see how each
teacher's students do in their subject.

**Classes I to XII.** Periodic tests are out of 20 (I-VIII) or 40 (IX-XII); Half Yearly / Yearly are 80 written +
20 internal in I-X (internal = PT scaled to 5 + portfolio 5 + project 5 + notebook 5, PT1 -> Half Yearly, PT2 ->
Yearly). Internal marks are optional: a file with only the written marks still works (the subject is worked out of
the written paper). XI-XII: 80, or 70 + 30 practical. AI in IX-X: 50 theory + 50 practical (viva 5, notebook 5,
file 10, test 30). ICT: written 30 from Class VII; not counted in I-VI. X and XII have a Preboard; Board results
(X and XII gazettes) stay separate. All of this is in `rules.json` -> `mark_schemes` and can be changed.

**Everything runs inside the browser on the school computer. Marks are never uploaded anywhere.**

---

## For teachers

1. Open the website in Chrome or Edge. The first visit takes a few seconds; after that it opens instantly and works offline.
2. **School results → Upload**: first pick the class (you get that class's template and only its subjects, and a
   question if a file looks like another class), then drop the marks file(s). Excel, old .xls, CSV, PDF and scanned
   *printed* sheets all work. The CBSE result gazette (.TXT) goes to **Board results** automatically.
   No file? **Type marks**: pick class, section, exam and subject - the names are already there, type only the marks.
   Marks on paper? Print the sheet there, write the marks by hand (one digit per box), and read a photo of it: every
   mark is shown next to its picture, unclear ones are marked, and the page total is checked.
3. **Check**: see what each column was understood as. Amber boxes need a click to confirm. Your choices are remembered.
4. **Review**: dashboard, every student, subjects, progress and report cards. Every chart and number has a **?**
   that plays a short walk-through with the same explanation written below it (all of them: **How it works**).
5. **Teachers**: add each teacher once (name, subject, classes) - or a 'Teachers' sheet in the file - to see how
   their students do in that subject, with a fair check against each student's own average.
6. **Download**: the Excel workbook (with or without buttons), PDF report cards, or a template filled with the students.

The first time you open an Excel file *with buttons*, Windows may block the macros:
right-click the file → **Properties** → tick **Unblock** → OK.

## What is in the Excel workbook

| Sheet | What it shows |
|---|---|
| Dashboard | Pick class / exam / section: students, class average, highest %, pass rate, top scorer, 4 charts |
| Report Card | Pick a student and exam: marks, %, class average, grade, gentle status, rule-based remarks, 3 charts |
| Subject Analysis | Averages, highest, lowest, pass %, theory vs practical, trend of a subject across exams |
| Marks Analysis | Two-exam scatter, spread of marks, grades pie, results doughnut |
| Progress | Overall % in every exam, the change, most improved, watch list |
| Marks VI, Marks XI PCM, ... | One sheet per class (and per stream in XI-XII) with only that class's subjects; each student's language / elective shares one column. **Correct marks here** and everything updates |
| Internals ... | Internal marks typed in parts (portfolio / project / notebook, AI practical); the PT part is a formula from the periodic test |
| Overview | One row per student per exam: total, overall %, result, rank |
| Teachers | Every teacher: their classes, exam by exam; and teachers of the same subject side by side |
| Subject Results | The engine: every subject result with status, %, grade, pass, label and the reason in words |
| Student Master | Every student once (names, parents, class, section, group, subjects) |
| Validation Report | Everything that was checked, with the exact cell it came from |
| Config | The rules (pass mark, thresholds, grades, leave codes); change the yellow cells |
| Source Data | An exact, protected copy of what was uploaded |

Totals, percentages, labels, reasons, ranks and charts are **Excel formulas**, so corrections flow through.
Only Excel 2010+ functions are used.

## Accuracy

* Marks are read exactly (decimals like 37.5 stay exact). Blank, zero and leave codes (AB / ML / DL / EX / NA) are always different things.
* Nothing is guessed: impossible marks (65 in a /30 practical, 45 in a /40 test, letters instead of numbers) are flagged and left out until corrected. The original file is never changed, and corrections are listed with the old value.
* Every result is computed **twice, in two independent ways**. If they ever disagree, no workbook is made.
* The workbook's formulas were checked in real Excel: all 144,229 formulas (sample: Classes VI, IX, X, XI, XII) give exactly the same answers as the website (`tools\check_excel.bat`).
* Two students with the same marks are always two students - students are told apart by admission / roll number. Only the same roll number twice in one sheet is flagged.
* The CBSE gazette reader counts every candidate and compares with CBSE's own "TOTAL CANDIDATES / PASS / COMPTT" line.

## For the developer

Everything is in plain Python (the engine) and plain JavaScript (the website). No build tools are needed.

| Double-click | What it does |
|---|---|
| `tools\setup.bat` | One time: installs the Python packages used for tests |
| `tools\run_tests.bat` | Runs all automatic tests (56 tests) |
| `tools\serve.bat` | Opens the website on this laptop (http://localhost:8765) |
| `tools\build_web.bat` | After changing anything in `core\`: copies it into `web\` |
| `tools\check_excel.bat` | Opens a test workbook in real Excel and compares every formula; runs the macros |

### Folders

```
core/markstudio/       the engine (Python) - the same code runs in the browser and in the tests
  config/              subjects.json, rules.json, groups.json, intents.json  (editable)
  readers.py           any file -> grids of text (Excel, xls, csv, PDF/scan words)
  gazette.py           the CBSE result gazette
  layout.py            works out what each column means (proposes; the teacher confirms)
  build.py             files + confirmed columns -> students and mark records, all checks
  calc.py / verify.py  the arithmetic, and the independent second calculation
  views.py             numbers for the website and the workbook (always the same)
  board.py             board results: best 5, PI, toppers, year on year, school vs boards
  query.py / nlu.py    questions in plain words -> approved operations only (tools/ask_bank.py: a local AI on the
                       developer's PC writes many phrasings to test the rules; tests/ask_bank.json keeps them)
  teachers.py          teacher analysis (cards + comparison, the fair check)
  commands.py          "change the Excel with words"
  excel/               workbook writer, board workbook, template, theme, macros (VBA)
  api.py               what the website calls
web/                   the website (publish this folder)
  js/worker.js         runs the Python engine in the browser (Pyodide)
  js/ai-worker.js      on-device AI: question understanding + voice (transformers.js)
  js/sheetscan.js      paper mark sheets: print, and read a photo (digit reader: assets/sheet/digits.json,
                       trained on drawn digits by tools/digits_train.py; test: js/sheettest.js)
  vendor/              all libraries, stored locally (nothing loads from other sites)
tests/                 automatic tests
tools/                 the .bat helpers
private/               real school files for testing ONLY - never published (in .gitignore)
```

### Changing rules

Use the website's **Settings** page (saved in the browser; Export / Import to share with other PCs),
or edit `core/markstudio/config/*.json` and run `build_web.bat`.

### Macros

The VBA project (`vbaProject.bin`) is generated directly from `core/markstudio/excel/macros.bas`
by `excel/vba.py`. No manual Excel steps are needed. Excel compiles the macros the first time the file is opened.

### Privacy

The page carries a Content-Security-Policy that only allows it to load its own files and, for the optional
on-device AI, the model files from Hugging Face. Student data has nowhere to go. The AI models run on the
computer's processor (no GPU needed); questions and voice recordings never leave the browser.
