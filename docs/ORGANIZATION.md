# Organization and Migration

## Scope

The 2026-10-15 cleanup separates source, tests, tools, and documentation.
Scientific rules and reference statistics are unchanged by the layout migration.
The old AI report export function was removed from `report_quality.py`.
The root notebook initializes module paths. Relocated modules resolve shared
resources with `workflow_paths.project_root()`. Use `python run_workflow.py test`.

## Retired Components

AI patient-report generation, cached report UI, credential helpers, key-entry widget,
configuration, installer, gateway smoke test, and direct tests were removed from
the active tree. Four mixed AI-era test modules and two verification scripts were
also preserved externally, not silently counted as passing tests. Their non-AI
coverage needs replacement where current reference/QC tests do not already cover it.

`assistant_visual_review.py` reads saved QC inspection evidence and does not call a
model. The parser's optional literature extraction backend is separate and off by default.

## Recovery

A full pre-cleanup backup and retired files are under the owner's external
`Documents/neurodesk_backups/` directory. `file_moves.json` records the moves.
The original manifest is historical; its hashes do not describe the reorganized tree.

## Deployment and Publication

The organized layout has been deployed and tested on the Neurodesk server.
This public distribution omits private runtime data and case-specific review scripts.
Deploy the source folders and launcher together, never just the new
notebook into an old flat installation. Preserve all remote case data and QC records.

Review tracked files as well as ignore rules before publication. Ignore rules cannot
remove previously published data. Runtime files, dated notes, and old installers
are excluded from the public view. Historical evaluation helpers and their tests
were moved to the external backup along with obsolete installers.

## Verification (2026-10-15)

- Notebook entry smoke test and source syntax checks passed locally.
- 34 focused layout, widget, QC, report-presentation, and pipeline tests passed.
- The JavaScript controls regression test passed with Node.
- The final active suite ran 242 tests: 235 passed, 2 failures, 5 errors.
  The same seven failing cases were reproduced against the pre-cleanup backup
  in the same environment; they were not introduced by the file moves.
- Existing failures involve the optional MRI viewer environment, zero-paper
  inventory coverage for newly added AD papers, and stale literature-count
  expectations. They are not hidden or marked as passing.
- SHA256 comparisons confirmed no changes to 101 reference-source files,
  13 existing output files, or the validation support file.

The full test command is intentionally not described as passing.
After deployment, 96 focused regression tests passed on the Neurodesk server.
The source catalog now includes all papers with extracted numeric data while
preserving the distinction between extracted data and patient-matched evidence.
Public notebooks contain no saved patient outputs. Patient measurements and QC
records are not part of this distribution.
