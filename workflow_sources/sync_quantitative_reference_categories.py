#!/usr/bin/env python3
"""Synchronize audited quantitative references into Disease and ROI indexes."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
QUANTITATIVE_PATH = ROOT / "quantitative_reference_statistics.json"
DISEASE_ROOT_PATH = ROOT / "Disease" / "disease_literature_sources.json"

DISEASE_FILES = {
    "AD": ROOT / "Disease" / "AD" / "ad_literature.json",
    "FTD": ROOT / "Disease" / "FTD" / "ftd_literature.json",
    "MCI": ROOT / "Disease" / "MCI" / "mci_literature.json",
    "VaD": ROOT / "Disease" / "VaD" / "vad_literature.json",
}
MIXED_DISEASE_PATH = (
    ROOT / "Disease" / "Mixed_Dementia" / "mixed_dementia_sources.json"
)

ROI_FILES = {
    "amygdala": ROOT / "ROI" / "Amygdala" / "amygdala_literature.json",
    "entorhinal cortex": (
        ROOT / "ROI" / "Entorhinal_Cortex" / "entorhinal_cortex_literature.json"
    ),
    "hippocampus": ROOT / "ROI" / "Hippocampus" / "hippocampus_literature.json",
    "medial temporal lobe": (
        ROOT / "ROI" / "Medial_Temporal_Lobe" / "medial_temporal_lobe_literature.json"
    ),
    "parahippocampal gyrus": (
        ROOT
        / "ROI"
        / "Parahippocampal_Gyrus"
        / "parahippocampal_gyrus_literature.json"
    ),
    "whole brain cortex": (
        ROOT / "ROI" / "Cortical_Thickness" / "cortical_thickness_literature.json"
    ),
    "white matter": ROOT / "ROI" / "White_Matter" / "white_matter_literature.json",
}

EVIDENCE_FIELDS = [
    "reference_id",
    "diagnosis",
    "roi_name",
    "hemisphere",
    "imaging_metric",
    "mean",
    "standard_deviation",
    "unit",
    "sample_size",
    "table_or_figure",
    "processing_pipeline",
    "processing_software",
    "processing_software_version",
    "atlas_name",
    "atlas_version",
    "parcellation_method",
    "atlas_compatibility_status",
    "comparison_compatible",
    "pathology_confirmation",
    "evidence_note",
    "extraction_method",
    "manual_review_status",
    "reviewed_by",
    "reviewed_at",
    "verification_note",
]


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(f"Expected a JSON array: {path}")
    return data


def write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def unique_values(rows: list[dict], field: str) -> list:
    values = {row.get(field) for row in rows if row.get(field) is not None}
    return sorted(values, key=lambda value: str(value).casefold())


def quantitative_rows(rows: list[dict]) -> list[dict]:
    return [
        {field: row.get(field) for field in EVIDENCE_FIELDS if field in row}
        for row in rows
    ]


def paper_entry(rows: list[dict], evidence_rows: list[dict], primary_roi=None) -> dict:
    first = rows[0]
    entry = {
        "paper_code": first["paper_code"],
        "source_title": first["source_title"],
        "doi": first.get("doi"),
        "year": first.get("year"),
        "source_url": first.get("source_url"),
        "diseases": unique_values(rows, "diagnosis"),
        "rois": unique_values(rows, "roi_name"),
        "imaging_metrics": unique_values(rows, "imaging_metric"),
        "evidence_use": (
            "Audited quantitative reference distributions; use only rows marked "
            "comparison_compatible after atlas, metric, hemisphere, and unit checks."
        ),
        "quantitative_evidence_source": (
            "workflow_sources/quantitative_reference_statistics.json"
        ),
        "quantitative_evidence_count": len(evidence_rows),
        "quantitative_evidence": quantitative_rows(evidence_rows),
    }
    if primary_roi is not None:
        entry["primary_roi"] = primary_roi
    return entry


def merge_entries(path: Path, generated: list[dict]) -> None:
    existing = load_json(path)
    generated_by_code = {entry["paper_code"]: entry for entry in generated}
    merged = []

    for entry in existing:
        replacement = generated_by_code.pop(entry.get("paper_code"), None)
        if replacement is None:
            merged.append(entry)
            continue
        updated = dict(entry)
        updated.update(replacement)
        merged.append(updated)

    merged.extend(sorted(generated_by_code.values(), key=lambda row: row["paper_code"]))
    write_json(path, merged)


def sync_disease_root(papers: dict[str, list[dict]]) -> None:
    existing = load_json(DISEASE_ROOT_PATH)
    existing_codes = {entry.get("paper_code") for entry in existing}
    additions = []
    for paper_code, rows in sorted(papers.items()):
        if paper_code in existing_codes or paper_code.startswith("ROI-"):
            continue
        first = rows[0]
        additions.append(
            {
                "paper_code": paper_code,
                "source_label": f"Audited quantitative reference {paper_code}",
                "input_value": first.get("source_url"),
                "source_group": "Audited quantitative disease evidence",
                "evidence_category": "quantitative_disease_evidence",
                "disease_focus": " / ".join(unique_values(rows, "diagnosis")),
                "source_title": first.get("source_title"),
                "doi": first.get("doi"),
                "year": first.get("year"),
                "evidence_use": (
                    "Paper-level source for manually verified quantitative reference "
                    "statistics. Numeric rows are stored in "
                    "quantitative_reference_statistics.json."
                ),
                "note": (
                    "Retain paper_code when linking source metadata to audited table rows."
                ),
            }
        )
    if additions:
        write_json(DISEASE_ROOT_PATH, existing + additions)


def main() -> None:
    quantitative = load_json(QUANTITATIVE_PATH)
    papers: dict[str, list[dict]] = defaultdict(list)
    for row in quantitative:
        papers[row["paper_code"]].append(row)

    sync_disease_root(papers)

    for diagnosis, path in DISEASE_FILES.items():
        generated = []
        for rows in papers.values():
            if diagnosis not in unique_values(rows, "diagnosis"):
                continue
            # Keep controls and other study groups beside the target diagnosis.
            generated.append(paper_entry(rows, rows))
        merge_entries(path, generated)

    generated_mixed = []
    target_diagnoses = set(DISEASE_FILES)
    for rows in papers.values():
        represented = target_diagnoses.intersection(unique_values(rows, "diagnosis"))
        if len(represented) >= 2:
            generated_mixed.append(paper_entry(rows, rows))
    merge_entries(MIXED_DISEASE_PATH, generated_mixed)

    for roi_name, path in ROI_FILES.items():
        generated = []
        for rows in papers.values():
            matching_rows = [row for row in rows if row.get("roi_name") == roi_name]
            if matching_rows:
                generated.append(paper_entry(rows, matching_rows, primary_roi=roi_name))
        merge_entries(path, generated)

    print(f"Synchronized {len(quantitative)} rows from {len(papers)} papers.")
    print(f"Disease category files: {len(DISEASE_FILES) + 1}")
    print(f"ROI category files: {len(ROI_FILES)}")


if __name__ == "__main__":
    main()
