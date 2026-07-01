# GPS Solutions Submission Readiness

Overall status: `NOT_SUBMISSION_READY`

Official pages to re-check before upload:

- GPS Solutions submission guidelines: https://link.springer.com/journal/10291/submission-guidelines
- GPS Solutions journal page: https://link.springer.com/journal/10291

## Manuscript Snapshot

- LaTeX class: `IEEEtran`
- Approximate word count: 5107
- Abstract words: 206
- Keywords: 5
- PDF pages: 10
- Referenced figures: 12 (.png)
- Compiled references: 31

## Audit Checks

| Status | Topic | Detail | Action |
| --- | --- | --- | --- |
| BLOCK | Submission file format | GPS Solutions currently requests Word-format submissions; no DOCX manuscript is present. | Prepare paper/submission/main.docx from the accepted manuscript text before submission. |
| WARN | Publisher template | Current draft uses IEEEtran; GPS Solutions submission should be converted to the journal Word/Springer format. | Use the current PDF as the technical draft, then create a Word submission version. |
| PASS | Abstract length | Abstract has 206 words. |  |
| PASS | Keywords | 5 keywords are present. |  |
| PASS | Regular paper length | Approximate manuscript word count is 5107. |  |
| PASS | PDF build | Compiled PDF exists with 10 pages. |  |
| PASS | Core manuscript sections | All core method-paper sections are present. |  |
| PASS | Statements and declarations | Funding, competing interests, data/code availability, ethics, and AI-tool statements are present. |  |
| PASS | Figure files | 12 referenced figures resolve on disk. |  |
| WARN | Final figure formats | All current figure sources are PNG (12 figures). | Prepare EPS/PDF line art or high-resolution TIFF/PNG source files according to final production instructions. |
| PASS | Reference coverage | 31 bibliography entries in the compiled draft. |  |
| PASS | Experiment matrix | Adaptive experiment matrix summary has 13 detector rows. |  |
| PASS | Temporal held-out validation | Temporal split exists with 107 calibration rows and 110 held-out rows. |  |
| SCIENCE_GAP | Route-held-out validation | Current configured routes are insufficient for independent route-held-out claims: routes=['full_data'], overlap=['full_data']. | Collect at least one additional clean/degraded route and keep train/test route names disjoint. |
| SCIENCE_GAP | Real spoofing evidence | The current attack evidence is synthetic/observation-level injection, not live RF or replay spoofing. | Add RF replay or public real-spoofing validation, or explicitly submit as synthetic-observation validation with strong limitations. |
| PASS | Generated metrics | Generated metrics are present; EA-SGLRT FA/min=5.944, temporal held-out FA/min=5.454. |  |

## Highest-Priority Remaining Work

1. Prepare the Word-format submission manuscript and final publisher-style title page.
2. Add at least one independent clean/degraded route for true route-held-out validation.
3. Add real RF replay/spoofing evidence or explicitly position the contribution as observation-level synthetic validation.
4. Prepare final production figures and confirm journal formatting immediately before upload.

## Reproducibility Commands

```bash
cmake -S . -B build
cmake --build build --target paper_pdf
cmake --build build --target paper_submission_audit
ctest --test-dir build --output-on-failure
```
