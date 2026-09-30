# Validation on real daily drilling reports (Equinor Volve)

The main evaluation (`backend/scripts/eval_extraction.py`) runs on **synthetic** reports, where the generator
knows the ground truth. This note records a small, separate check on **real** reports. Read the caveats: the
sample is tiny and the second result is not a clean held-out test.

## Data
- Equinor Volve open data, `Well_technical_data/Daily Drilling report - PDF Version/`, obtained through the
  Databricks Marketplace listing after accepting the Equinor Open Data Licence. The reports are **not**
  redistributed here (`data/` is gitignored).
- 20 reports from one wellbore (15/9-19 A, July–August 1997) for development.
- 20 reports from 20 other wellbores (1992–2015), chosen by a content-blind rule (the middle report of each of
  the 20 largest wellbores), for testing.

## What real reports required
The synthetic layout has an "OPERATIONS SUMMARY" heading; real Volve reports use a "Summary report" layout
(header block, activity summary, an operations table whose cells wrap across lines, sometimes mid-word). The
first run of the unmodified pipeline found **0 events** because the layout parser skipped every page.

Changes made: a parser for that layout (`parse_summary_report`), extra phrasings (`got stuck`, `tight hole`,
`packed-off`, `lost circ`, `TDS stalled`, `attempts to pass obstruction`), several hazards per sentence, merging of
repeated descriptions of one incident, no `overpressure` from a bare "drilling break", no torque event for a
deliberate "torqued up ... to N" procedure, and space-separated thousands in depths ("2 519 m").
Synthetic results were re-run after the changes and are unchanged (DDR F1 0.98, merged F1 0.97).

## Results
| Stage | Reports | Real incidents (hand-labelled) | Found | False alerts |
|---|---|---|---|---|
| Original pipeline, development set | 20 | 5 | 0 | 0 |
| First fixes, development set (tuned on it) | 20 | 5 | 5 | 0 |
| First fixes, **held-out** set (clean) | 20 | 6 | 4 | 1 |
| After a second round of fixes, same set | 20 | 6 | 6 | 0 |

**The clean held-out result is 4 of 6 incidents found, precision 4 of 5** (2 of the 3 clear-cut incidents). The
last row is *not* a held-out result: the second round of fixes (`pack- off` spelling, obstruction wording, the
torque rule, space-separated depths) was written after seeing those misses, so those reports became development
data. A fresh set would be needed to measure the improvement honestly.

## Caveats
- One labeller (the author), some borderline calls (3 of the 6 held-out incidents are "weak").
- Only 3 of the 20 held-out reports contain any incident, so a single label changes the figures a lot.
- Rule-based extraction tuned on a handful of reports will not transfer unchanged to other operators' wording.
- Reports with no operations table fall back to the one-paragraph summary.
