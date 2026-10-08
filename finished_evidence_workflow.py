"""Run the complete source-transparent FreeSurfer evidence workflow."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from neurodesk_literature_to_pgsql import (
    apply_atlas_translation,
    metadata_completeness_report,
    summarize_atlas_translation,
)


# Canonical Neurodesk locations first; later entries are local-checkout fallbacks.
REQUIRED_FILE_CANDIDATES = {
    "atlas_translation": (
        "workflow_sources/atlas_translation/atlas_translation_registry.json",
        "atlas_translation_registry.json",
        "workflow_sources/atlas_translation/minimal_atlas_translation.json",
        "minimal_atlas_translation.json",
    ),
    "mmc_models": (
        "workflow_sources/external_validators/mmc_dk_models.json",
        "mmc_dk_models.json",
    ),
    "literature_manifest": (
        "workflow_sources/literature_source_registry.json",
        "literature_source_registry.json",
    ),
    "disease_registry": (
        "workflow_sources/Disease/disease_literature_sources.json",
        "disease_literature_sources.json",
    ),
    "roi_registry": (
        "workflow_sources/ROI/roi_literature_sources.json",
        "roi_literature_sources.json",
    ),
    "quantitative_references": (
        "workflow_sources/quantitative_reference_statistics.json",
        "quantitative_reference_statistics.json",
    ),
}

FEATURE_CSV_CANDIDATES = (
    "outputs/pilot_freesurfer_structural_features.csv",
    "pilot_freesurfer_structural_features.csv",
    "/home/jovyan/outputs/pilot_freesurfer_structural_features.csv",
)
FS_ROOT_CANDIDATES = (
    "derivatives/freesurfer",
    "/home/jovyan/derivatives/freesurfer",
)
DATASET_ROOT_CANDIDATES = (
    "disc1",
    "/home/jovyan/neurodesk/disc1",
)

# Kept for callers that still read the original relative paths.
REQUIRED_FILES = {
    name: candidates[0] for name, candidates in REQUIRED_FILE_CANDIDATES.items()
}


def _first_existing(root: Path, candidates: tuple[str, ...], env_var: str | None = None) -> Path:
    """Return the first path that exists, honouring an environment override."""
    if env_var:
        override = os.environ.get(env_var)
        if override:
            return Path(override).expanduser()
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return path
    first = Path(candidates[0])
    return first if first.is_absolute() else root / first


def resolve_required_files(project_dir: str | Path) -> dict[str, Path]:
    """Map each required resource to the first existing candidate path."""
    root = Path(project_dir).resolve()
    return {
        name: _first_existing(root, candidates)
        for name, candidates in REQUIRED_FILE_CANDIDATES.items()
    }


def resolve_workflow_inputs(
    project_dir: str | Path = ".",
    feature_csv: str | Path | None = None,
    fs_root: str | Path | None = None,
    dataset_root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Resolve notebook and library paths across Neurodesk and a local checkout."""
    root = Path(project_dir).resolve()
    return {
        "project_dir": root,
        "feature_csv": Path(feature_csv) if feature_csv else _first_existing(
            root, FEATURE_CSV_CANDIDATES, "ATLAS_STRUCTURAL_FEATURES_CSV"
        ),
        "fs_root": Path(fs_root) if fs_root else _first_existing(
            root, FS_ROOT_CANDIDATES, "ATLAS_FREESURFER_ROOT"
        ),
        "dataset_root": Path(dataset_root) if dataset_root else _first_existing(
            root, DATASET_ROOT_CANDIDATES, "ATLAS_DATASET_ROOT"
        ),
        "output_dir": Path(output_dir) if output_dir else root / "finished_workflow_outputs",
        **resolve_required_files(root),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_resource_json(path: Path) -> bool:
    """Exclude macOS AppleDouble and hidden metadata files from source discovery."""
    return path.suffix.lower() == ".json" and not any(
        part.startswith(".") for part in path.parts
    )


def validate_inputs(
    project_dir: str | Path,
    feature_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Return one preflight row per required input and preserve exact paths."""
    paths = resolve_workflow_inputs(project_dir, feature_csv=feature_csv)
    rows = []
    inputs = {"freesurfer_features": paths["feature_csv"]}
    inputs.update({name: paths[name] for name in REQUIRED_FILE_CANDIDATES})
    for name, path in inputs.items():
        exists = path.is_file()
        rows.append(
            {
                "resource": name,
                "path": str(path),
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else pd.NA,
                "sha256": _sha256(path) if exists else pd.NA,
                "status": "ready" if exists else "missing",
            }
        )
    return pd.DataFrame(rows)


def resource_manifest(project_dir: str | Path) -> pd.DataFrame:
    """Inventory project JSON sources while excluding generated databases."""
    root = Path(project_dir)
    source_root = root / "workflow_sources"
    if not source_root.exists():
        return pd.DataFrame(
            columns=["resource_path", "resource_type", "record_count", "size_bytes", "sha256"]
        )
    rows = []
    for path in sorted(source_root.rglob("*.json")):
        if not _is_resource_json(path):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            record_count = len(data)
        elif isinstance(data, dict):
            record_count = len(data.get("records", data.get("mappings", data.get("models", data.get("cohorts", [])))))
        else:
            record_count = 0
        rows.append(
            {
                "resource_path": str(path.relative_to(root)),
                "resource_type": "JSON source registry",
                "record_count": record_count,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return pd.DataFrame(rows)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _category_records(root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Read the richer disease/ROI category indexes used for browsing and audit."""
    records = []
    for section in ("Disease", "ROI"):
        for path in sorted((root / "workflow_sources" / section).glob("*/*.json")):
            if not _is_resource_json(path):
                continue
            for item in _read_json_list(path):
                records.append((section, item))
    return records


def paper_inventory(project_dir: str | Path) -> pd.DataFrame:
    """Build the visible, deduplicated list of papers included in the workflow."""
    root = Path(project_dir)
    records = []
    category_items = _category_records(root)
    if not category_items:
        required = resolve_required_files(root)
        category_items = [
            (kind, item)
            for kind, key in (
                ("Disease", "disease_registry"),
                ("ROI", "roi_registry"),
            )
            if required[key].is_file()
            for item in _read_json_list(required[key])
        ]
    for kind, item in category_items:
        records.append(
            {
                "paper_id": item.get("paper_id") or item.get("paper_code"),
                "source_title": item.get("source_title"),
                "year": item.get("year"),
                "doi": item.get("doi"),
                "source_url": item.get("source_url"),
                "diseases": ", ".join(item.get("diseases", [])),
                "rois": ", ".join(item.get("rois", [])),
                "registry_sections": kind,
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame

    def combine(values: pd.Series) -> str:
        return ", ".join(sorted({str(v) for v in values if pd.notna(v) and str(v)}))

    return (
        frame.groupby("paper_id", dropna=False, as_index=False)
        .agg(
            source_title=("source_title", "first"),
            year=("year", "first"),
            doi=("doi", "first"),
            source_url=("source_url", "first"),
            diseases=("diseases", combine),
            rois=("rois", combine),
            registry_sections=("registry_sections", combine),
        )
        .sort_values(["year", "paper_id"], na_position="last")
        .reset_index(drop=True)
    )


def qualitative_reference_records(project_dir: str | Path) -> list[dict[str, Any]]:
    """Return extracted records only; category indexes remain in the audit browser."""
    from literature_audit import build_literature_audit, qualitative_candidates
    return qualitative_candidates(build_literature_audit(project_dir))


def _quality_checks(
    subjects: list[str],
    features: pd.DataFrame,
    normative: pd.DataFrame,
    links: pd.DataFrame,
) -> pd.DataFrame:
    checks = []
    observed = set(features["subject_id"].astype(str))
    checks.append(("requested_subjects_present", set(subjects).issubset(observed), f"{len(set(subjects) & observed)}/{len(subjects)}"))
    for field in ["age", "sex", "estimated_total_intracranial_volume", "scanner_field_strength", "scanner_manufacturer"]:
        values = features.groupby("subject_id")[field].first()
        complete = values.notna() & ~values.astype(str).str.lower().isin(["", "nan", "none", "unknown"])
        checks.append((f"subject_{field}_complete", bool(complete.all()), f"{int(complete.sum())}/{len(values)}"))
    calculated = normative[normative["calculation_status"].eq("calculated")]
    per_subject = calculated.groupby("subject_id").size().reindex(subjects, fill_value=0)
    checks.append(("mmc_normative_results_generated", bool((per_subject > 0).all()), ", ".join(f"{sid}:{count}" for sid, count in per_subject.items())))
    label_blind = "diagnosis" not in normative.columns
    checks.append(("recorded_diagnosis_excluded_from_model", label_blind, "diagnosis is absent from normative result/model inputs"))
    if links.empty:
        qualitative_only = True
    else:
        qualitative_only = bool((links["numeric_use"] == False).all())  # noqa: E712
    checks.append(("cross_method_links_qualitative_only", qualitative_only, f"{len(links)} links"))
    return pd.DataFrame(checks, columns=["check", "passed", "detail"])


def run_finished_workflow(
    project_dir: str | Path = ".",
    feature_csv: str | Path | None = None,
    fs_root: str | Path | None = None,
    dataset_root: str | Path | None = None,
    subject_ids: list[str] | None = None,
    output_dir: str | Path | None = None,
    reference_focus: str = 'all',
) -> dict[str, Any]:
    """Run every stage and return display-ready tables and report text."""
    try:
        from mmc_normative_workflow import (
            build_report,
            enrich_covariates,
            evaluate_features,
            load_models,
            qualitative_links,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "mmc_normative_workflow.py is required to compute age-adjusted MMC "
            "results, qualitative literature links, and individual reports. "
            "Place it next to finished_evidence_workflow.py."
        ) from exc

    paths = resolve_workflow_inputs(
        project_dir,
        feature_csv=feature_csv,
        fs_root=fs_root,
        dataset_root=dataset_root,
        output_dir=output_dir,
    )
    root = paths["project_dir"]
    feature_csv = paths["feature_csv"]
    fs_root = paths["fs_root"]
    dataset_root = paths["dataset_root"]
    output = paths["output_dir"]
    output.mkdir(parents=True, exist_ok=True)

    preflight = validate_inputs(root, feature_csv)
    if not preflight["exists"].all():
        missing = preflight.loc[~preflight["exists"], "path"].tolist()
        raise FileNotFoundError("Missing required workflow inputs: " + ", ".join(missing))

    resources = resource_manifest(root)
    from literature_audit import build_literature_audit, qualitative_candidates
    from reference_focus import filter_audit, focus
    reference_focus = focus({'reference_focus': reference_focus})
    audit = filter_audit(build_literature_audit(root, output), reference_focus)
    papers = audit['papers']
    features = pd.read_csv(feature_csv)
    if subject_ids is None:
        subject_ids = sorted(features["subject_id"].dropna().astype(str).unique().tolist())
    features = features[features["subject_id"].astype(str).isin(subject_ids)].copy()
    if features.empty:
        raise ValueError("No requested subjects were found in the FreeSurfer feature CSV")
    features = enrich_covariates(features, fs_root, dataset_root)
    from segmentation_holds import annotate_features, apply_normative_holds
    features = annotate_features(dict(project_dir=root, fs_root=fs_root), features)

    from comparison_atlas import prepare_features
    translated = prepare_features(features, paths["atlas_translation"])
    translation_summary = summarize_atlas_translation(translated)
    metadata_summary = metadata_completeness_report(features)

    models = load_models(paths["mmc_models"])
    # Retain model provenance; remove held derived values before any output or linking.
    model_inputs = translated.drop(columns=['qc_hold_reason'], errors='ignore')
    normative = evaluate_features(model_inputs, models)
    from potvin_subcortical import augment_normative
    normative = augment_normative({'project_dir': root, 'comparison_features': model_inputs}, normative)
    normative = apply_normative_holds(translated, normative)
    references = qualitative_candidates(audit)
    links = qualitative_links(normative, references)
    checks = _quality_checks(subject_ids, features, normative, links)

    reports = {}
    for subject_id in subject_ids:
        report = build_report(normative, links, subject_id)
        reports[subject_id] = report
        (output / f"{subject_id}_brain_morphology_report.md").write_text(
            report, encoding="utf-8"
        )

    preflight.to_csv(output / "input_preflight.csv", index=False)
    resources.to_csv(output / "resource_manifest.csv", index=False)
    papers.to_csv(output / "included_papers.csv", index=False)
    features.to_csv(output / "subject_features_with_covariates.csv", index=False)
    translated.to_csv(output / "atlas_translation_audit.csv", index=False)
    normative.to_csv(output / "normative_roi_results.csv", index=False)
    links.to_csv(output / "qualitative_literature_links.csv", index=False)
    checks.to_csv(output / "quality_checks.csv", index=False)

    valid = normative[normative["calculation_status"].eq("calculated")]
    run_manifest = {
        "workflow_name": "Neurodesk finished evidence workflow",
        "workflow_version": "V0.4-source-audit",
        "reference_focus": reference_focus,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "subject_ids": subject_ids,
        "input_feature_csv": str(feature_csv),
        "atlas_translation_registry": str(paths["atlas_translation"]),
        "output_dir": str(output),
        "resource_json_files": len(resources),
        "included_unique_papers": len(papers),
        "structural_feature_rows": len(features),
        "normative_results_calculated": len(valid),
        "outside_pointwise_95pi": int(valid["range_status"].ne("within_95pi").sum()),
        "qualitative_literature_links": len(links),
        "quality_checks_passed": int(checks["passed"].sum()),
        "quality_checks_total": len(checks),
        "interpretation_scope": "research description of brain morphology and source-linked literature context",
        "model_excludes_recorded_diagnosis": True,
    }
    (output / "workflow_run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "reference_focus": reference_focus,
        "project_dir": root,
        "fs_root": fs_root,
        "output_dir": output,
        "run_manifest": run_manifest,
        "preflight": preflight,
        "resources": resources,
        "papers": papers,
        "literature_audit": audit,
        "features": features,
        "comparison_features": translated,
        "metadata_summary": metadata_summary,
        "translated": translated,
        "translation_summary": translation_summary,
        "normative": normative,
        "links": links,
        "checks": checks,
        "reports": reports,
    }
