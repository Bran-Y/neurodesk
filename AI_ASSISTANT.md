# Optional AI evidence explanation

Selected model: `glm-5.3-flash`. Endpoint: `https://llm.chudian.site/v1/chat/completions`.
`ai_settings.json` contains public configuration only. Never add a key to this file.

## Use

1. Generate the ordinary numeric report in `00_START_HERE.ipynb`.
2. The private `.env` beside `ai_credentials.py` provides `AIGATE_API_KEY` automatically,
   including after a kernel restart. Run the **AI connection** status cell if desired:

```python
from ai_credentials import load_api_key
print('AI key configured' if load_api_key() else 'Private .env is not configured')
```

3. To create or replace `.env`, run `python ai_credentials.py` in the Jupyter terminal
   and enter the key at the hidden prompt. Never put it in the command or notebook.
   The helper creates mode 600; only the owner can read/write it. `.env` is ignored
   by Git and must be excluded from all transfer/release archives. Our update ZIPs
   use explicit public-file allowlists, not whole-directory archives.
   The file is plaintext, not encrypted; server administrators can still read it.
   An existing in-memory key takes precedence. After rotating the file, clear the
   in-memory key or restart the kernel. Clearing memory does not delete `.env`.
4. The AI report appears automatically below the numeric report. No separate AI
   Generate button, preview or manual save is required. This workflow's owner requested
   automatic transmission for the selected subject after the third-party disclosure;
   this authorisation is recorded in `ai_report_policy.json`.
5. Evidence is prepared internally. The report displays a patient-specific conclusion,
   supporting findings and linked literature. Supporting/opposing details are collapsed.
   If the supplied evidence cannot distinguish a disease, the conclusion says so;
   no most-likely diagnosis, percentage or known label is fabricated.
6. Drafts and full audit inputs are saved in `outputs/.ai_report_cache` with directory
   mode 700 and file mode 600. These contain sensitive health information and must
   not be included in public packages. Cache identity includes the local subject,
   complete evidence hash, model, endpoint, prompt version and output-token limit.
   Identical inputs reuse the stored draft without a second API call. The numeric
   report is not overwritten. Set `auto_generate` to false to stop new requests.

```python
from ai_evidence_assistant import clear_api_key
clear_api_key()
```

Changing subjects clears the previous AI output and starts/reuses the selected case's
report after a short debounce. Only the selected case is sent, not a batch. Network
I/O runs in a worker thread so the notebook UI remains responsive. A late response
cannot replace another patient's report. Pending, failed or uncertain requests are
retained without automatic retries, including after a kernel restart. T2 reports
do not enter this T1 evidence assistant.

Columnar transport preserves every evidence row and value while avoiding repeated
field names and common values. Original evidence IDs and paper links remain intact.
The audit keeps hashes for both the full logical input and the actual compact input.
Request profile v4 explicitly sets `reasoning_effort=low` and JSON output; the model
is explaining already computed evidence rather than recalculating or diagnosing.
The upstream default is max effort, which can add considerable latency. The
180-second wait remains bounded. Reasoning effort, elapsed time and token usage
are recorded where available. Old failed request records are preserved.
API semantics: https://docs.z.ai/api-reference/llm/chat-completion.

## Boundaries

### Exploratory candidates (v5/v6, 2026-09-23)

Removed the categorical ban on PD candidate interpretation and PD mixed evidence.
The AI may now report `Possible PD` or `Possible AD` with patient-linked citations,
or a `Control-like pattern`; these are exploratory associations, not diagnoses.
Both `possible_association` and `mixed_evidence` appear directly in the report.
The validator audits cited directions: for PD, an available measured outlier can
align with or oppose the published effect direction. Normal-range, missing and
zero-effect rows are neutral. AD/Control context uses the supplied marginal
comparison, not a subject label. Ties and atypical-in-both comparisons are neutral.
Contrary context cannot be hidden to obtain a support-only candidate status.
Age extrapolation remains a warning rather than a hard exclusion.
V6 also sends a precomputed per-condition eligibility index, so the AI selects
citations from explicitly assigned supporting/opposing lists rather than inferring
their direction from a large columnar table. All original evidence remains supplied.

These are transparent exploratory rules, not validated diagnostic criteria.
Findings that cite unassessed normative measurements display the verified calculation
statuses instead of AI prose. The raw model response is retained unchanged in the
private audit; this protects against treating missing norms as normality. This is
not comprehensive semantic validation of every model claim.
There is no forced PD result, diagnostic percentage, or claim of diagnostic accuracy.
The new prompt version uses a different cache key; old reports are preserved but
not reused as newly generated results. Recreate the panel after reloading the module
or restarting the kernel to apply the update. A new authorised API request may occur.

Only allowlisted numeric/categorical metadata, normative results, ENIGMA PD group
effects and available exploratory Zheng comparisons are sent. IDs, known diagnoses,
local paths, clinical free text and MRI files are excluded. This is data minimization,
not a guarantee of irreversible anonymization. Gateway retention, downstream providers
and institutional permission must be checked before real patient data is sent.

Python supplies all numbers. The model writes qualitative explanations and cites
existing evidence IDs. Unknown citations, unavailable rows used as support/opposition,
new numerical prose, malformed/truncated output and an unexpected model ID are rejected.
These checks do not verify the medical truth of prose; every draft needs human review.
Group effects do not become a PD classifier. No calibrated probability is generated.
No tool calls, automatic retries, external searches or automatic report replacement.

The key previously pasted into chat should be rotated. No key is bundled here.
