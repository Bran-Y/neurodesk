# Explicit PD Reference Focus

Select `References: PD + Potvin (no AD comparison)` before generating reports,
or set `reference_focus` to `PD` in the case configuration. The UI saves explicit
selections to the selected configuration, preserving its original as a private
backup. `Use saved configuration` restores that scope on a new session.

The scope is a researcher-selected comparison question, not a diagnosis, cohort
label, prior probability, or evidence that the patient has PD. Identity and known
diagnoses do not select it automatically. Existing configurations default to
`all` until an explicit selection is made.

## Actual Computation

- Keep Potvin normative calculations and their missing-data statuses.
- Compare measured features through Atlas Translation with ENIGMA PD summary
  statistics (Laansma et al., 2021, https://doi.org/10.1002/mds.28706).
- Filter source records before qualitative patient joins in the finished workflow.
- Skip Zheng AD/Control computation in the concise report, patient ledger,
  compatibility view, disease evidence view, source counts, and AI payload.
- Limit the AI candidate contract to PD in this scope; preserve uncertainty.
- Include reference scope in exported configuration, run manifest and AI cache
  identity. Old all-reference AI results cannot satisfy the new input hash.

ENIGMA data are PD-versus-Control group effects, not individual PD distributions
or a validated classifier. A normal-range feature does not exclude PD. Matching
region names alone is not disease support. Weak effects remain weak context.
Other diseases are not evaluated in PD scope, not excluded.

## Verification

74 local regression tests passed, including actual routing tests that raise if
an AD comparator is invoked in PD scope; report/export paths, candidate rejection,
cache separation, unchanged default scope, and persistent private configuration
backups are tested. Current web case was regenerated with PD-only disease evidence;
the visible AI report cites Potvin and ENIGMA PD, not Zheng AD/Control.
