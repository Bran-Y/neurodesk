from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import pandas as pd

try:
    import requests
except ModuleNotFoundError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    BeautifulSoup = None

try:
    from pypdf import PdfReader
except ModuleNotFoundError:
    try:
        from PyPDF2 import PdfReader
    except ModuleNotFoundError:
        PdfReader = None

try:
    from openpyxl import Workbook
except ModuleNotFoundError:
    Workbook = None


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
WHITESPACE_RE = re.compile(r"\s+")

DIAGNOSIS_KEYWORDS = {
    "AD": ["alzheimer", "ad "],
    "bvFTD": [
        "behavioral variant frontotemporal dementia",
        "behavioural variant frontotemporal dementia",
        "behavioral variant ftd",
        "behavioural variant ftd",
        "bvftd",
        "frontal variant frontotemporal dementia",
        "frontotemporal dementia, behavioral variant",
        "pick's disease",
        "picks disease",
    ],
    "svPPA": [
        "semantic variant primary progressive aphasia",
        "svppa",
        "semantic dementia",
    ],
    "nfvPPA": [
        "nonfluent variant primary progressive aphasia",
        "non-fluent variant primary progressive aphasia",
        "agrammatic variant primary progressive aphasia",
        "nonfluent/agrammatic variant primary progressive aphasia",
        "non-fluent/agrammatic variant primary progressive aphasia",
        "progressive nonfluent aphasia",
        "progressive non-fluent aphasia",
        "pnfa",
        "nfvppa",
    ],
    "lvPPA": [
        "logopenic variant primary progressive aphasia",
        "logopenic progressive aphasia",
        "lvppa",
        "lppa",
    ],
    "PPA": ["primary progressive aphasia"],
    "FTD-ALS": [
        "frontotemporal dementia with amyotrophic lateral sclerosis",
        "frontotemporal dementia and amyotrophic lateral sclerosis",
        "frontotemporal dementia with motor neuron disease",
        "ftd-als",
        "ftd als",
        "ftd-mnd",
        "ftd mnd",
        "als-ftd",
        "als ftd",
    ],
    "PSP": ["progressive supranuclear palsy", "psp"],
    "CBS": ["corticobasal syndrome", "corticobasal degeneration", "cbs", "cbd"],
    "FTD": ["frontotemporal dementia", "frontotemporal degeneration", "frontotemporal lobar degeneration", "ftd"],
    "DLB": ["lewy body", "dlb"],
    "VaD": ["vascular dementia", "vad", "white matter hyperintens"],
    "MCI": ["mild cognitive impairment", "mci"],
    "Control": ["control", "healthy"],
    "Dementia": ["dementia"],
}

FTD_SPECIFIC_DIAGNOSES = {"bvFTD", "svPPA", "nfvPPA", "lvPPA", "FTD-ALS", "PSP", "CBS"}
PPA_SPECIFIC_DIAGNOSES = {"svPPA", "nfvPPA", "lvPPA"}

ROI_ALIASES = {
    "hippocampus": "hippocampus",
    "hippocampal": "hippocampus",
    "total_hippocampus": "hippocampus",
    "entorhinal": "entorhinal cortex",
    "entorhinal cortex": "entorhinal cortex",
    "parahippocampal": "parahippocampal gyrus",
    "parahippocampal gyrus": "parahippocampal gyrus",
    "amygdala": "amygdala",
    "medial temporal lobe": "medial temporal lobe",
    "medial temporal": "medial temporal lobe",
    "mtl": "medial temporal lobe",
    "posterior cingulate": "posterior cingulate cortex",
    "posterior cingulate cortex": "posterior cingulate cortex",
    "inferior parietal": "inferior parietal cortex",
    "inferior parietal cortex": "inferior parietal cortex",
    "temporal cortex": "temporal cortex",
    "temporal lobe": "temporal cortex",
    "superior temporal": "superior temporal cortex",
    "superior temporal cortex": "superior temporal cortex",
    "middle temporal": "middle temporal cortex",
    "middle temporal cortex": "middle temporal cortex",
    "inferior temporal": "inferior temporal cortex",
    "inferior temporal cortex": "inferior temporal cortex",
    "frontal cortex": "frontal cortex",
    "frontal lobe": "frontal cortex",
    "anterior temporal": "anterior temporal cortex",
    "anterior temporal cortex": "anterior temporal cortex",
    "insula": "insula",
    "insular": "insula",
    "anterior cingulate": "anterior cingulate cortex",
    "anterior cingulate cortex": "anterior cingulate cortex",
    "white matter": "white matter",
    "wm": "white matter",
    "whole brain cortex": "whole brain cortex",
    "whole-brain cortex": "whole brain cortex",
}

# Substring alias matching must try the most specific alias first. In insertion
# order "hippocampal" precedes "parahippocampal" and "temporal cortex"
# precedes "inferior temporal", so a shorter alias would capture the label.
ROI_ALIAS_MATCH_ORDER = sorted(ROI_ALIASES, key=len, reverse=True)

NON_WHITE_MATTER_RE = re.compile(r"non[-_ ]?(wm|white)")
QUALIFIED_WHITE_MATTER_RE = re.compile(r"(cerebell\w*|brainstem|brain[-_ ]stem)[-_ ]+white[-_ ]matter")
HEMISPHERE_PREFIX_RE = re.compile(r"^(left|right|lh|rh)[-_ ]+")

METRIC_ALIASES = {
    "surface": "surface_area",
    "surface area": "surface_area",
    "surface_area": "surface_area",
    "cortical_thickness": "cortical_thickness",
    "cortical thickness": "cortical_thickness",
    "cortical thinning": "cortical_thickness",
    "thickness": "cortical_thickness",
    "roi_volume": "roi_volume",
    "volume": "roi_volume",
    "regional volume": "roi_volume",
    "regional_volumes": "roi_volume",
    "hippocampal_volume": "hippocampal_volume",
    "hippocampal volume": "hippocampal_volume",
    "total_hippocampus": "hippocampal_volume",
    "white_matter_hyperintensity": "white_matter_hyperintensity",
    "white matter hyperintensity": "white_matter_hyperintensity",
    "white matter hyperintensities": "white_matter_hyperintensity",
}

DIAGNOSIS_SIGNATURES = {
    "AD": {
        "rois": {"hippocampus", "entorhinal cortex", "parahippocampal gyrus", "posterior cingulate cortex", "inferior parietal cortex"},
        "metrics": {"roi_volume", "hippocampal_volume", "cortical_thickness"},
    },
    "bvFTD": {
        "rois": {"frontal cortex", "anterior temporal cortex", "insula", "anterior cingulate cortex", "temporal cortex"},
        "metrics": {"cortical_thickness", "roi_volume"},
    },
    "svPPA": {
        "rois": {"anterior temporal cortex", "temporal cortex", "entorhinal cortex", "parahippocampal gyrus"},
        "metrics": {"cortical_thickness", "roi_volume"},
    },
    "nfvPPA": {
        "rois": {"frontal cortex", "insula", "anterior cingulate cortex"},
        "metrics": {"cortical_thickness", "roi_volume"},
    },
    "lvPPA": {
        "rois": {"inferior parietal cortex", "posterior cingulate cortex", "temporal cortex", "hippocampus"},
        "metrics": {"cortical_thickness", "roi_volume"},
    },
    "FTD-ALS": {
        "rois": {"frontal cortex", "temporal cortex", "white matter"},
        "metrics": {"cortical_thickness", "roi_volume", "white_matter_hyperintensity"},
    },
    "PSP": {
        "rois": {"frontal cortex", "anterior cingulate cortex"},
        "metrics": {"cortical_thickness", "roi_volume"},
    },
    "CBS": {
        "rois": {"frontal cortex", "inferior parietal cortex", "white matter"},
        "metrics": {"cortical_thickness", "roi_volume", "white_matter_hyperintensity"},
    },
    "DLB": {
        "rois": {"posterior cingulate cortex", "temporal cortex", "hippocampus"},
        "metrics": {"roi_volume", "cortical_thickness"},
    },
    "VaD": {
        "rois": {"white matter", "frontal cortex"},
        "metrics": {"white_matter_hyperintensity", "roi_volume"},
    },
}

MODALITY_KEYWORDS = {
    "MRI": ["mri", "structural mri", "t1", "brain volume"],
    "PET": ["pet", "amyloid", "fdg"],
    "DWI": ["diffusion", "dwi"],
    "Perfusion": ["perfusion", "asl"],
}

ROI_KEYWORDS = [
    "hippocampus",
    "entorhinal cortex",
    "parahippocampal gyrus",
    "posterior cingulate cortex",
    "inferior parietal cortex",
    "temporal cortex",
    "frontal cortex",
    "anterior temporal cortex",
    "insula",
    "anterior cingulate cortex",
    "white matter",
]

SYMPTOM_KEYWORDS = {
    "memory impairment": ["memory impairment", "memory loss", "forgetfulness"],
    "cognitive decline": ["cognitive decline", "decline in cognition", "cognitive impairment"],
    "executive dysfunction": ["executive dysfunction", "executive function"],
    "language disturbance": ["language disturbance", "language impairment", "aphasia"],
    "behavioural change": ["behavioural changes", "behavioral changes", "altered behaviour", "altered behavior"],
    "apathy": ["apathy"],
    "disinhibition": ["disinhibition"],
    "mood change": ["mood", "depression", "anxiety"],
    "functional decline": ["daily functioning", "functional independence", "functional decline"],
    "visuospatial impairment": ["visuospatial"],
    "hallucinations": ["hallucination", "hallucinations"],
    "fluctuating cognition": ["fluctuating cognition", "cognitive fluctuations"],
    "parkinsonism": ["parkinsonism"],
    "cortical thickness": ["cortical thickness", "cortical thinning"],
    "hippocampus": ["hippocampus", "hippocampal atrophy"],
    "entorhinal cortex": ["entorhinal cortex", "entorhinal atrophy"],
    "parahippocampal gyrus": ["parahippocampal gyrus", "parahippocampal"],
    "posterior cingulate cortex": ["posterior cingulate cortex", "posterior cingulate"],
    "inferior parietal cortex": ["inferior parietal cortex", "inferior parietal"],
    "temporal cortex": ["temporal cortex", "temporal lobe atrophy"],
    "frontal cortex": ["frontal cortex", "frontal lobe atrophy"],
    "anterior temporal cortex": ["anterior temporal cortex", "anterior temporal"],
    "insula": ["insula", "insular"],
    "anterior cingulate cortex": ["anterior cingulate cortex", "anterior cingulate"],
    "white matter hyperintensities": ["white matter hyperintensities", "white matter lesions"],
}


@dataclass
class SourceDocument:
    input_value: str
    source_type: str
    source_label: str
    raw_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiteratureRecord:
    source_label: str
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    authors: list[str] = field(default_factory=list)
    study_design: str | None = None
    population: str | None = None
    diagnoses: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    rois: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    sex_scope: list[str] = field(default_factory=list)
    imaging_metrics: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    abstract_like_summary: str | None = None
    extraction_mode: str = "heuristic"
    source_type: str | None = None
    source_path_or_url: str | None = None


def read_pdf_bytes(data: bytes) -> str:
    if PdfReader is None:
        raise ModuleNotFoundError("Neither pypdf nor PyPDF2 is installed in this environment")

    reader = PdfReader(BytesIO(data))
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def load_source(input_value: str) -> SourceDocument:
    if input_value.startswith(("http://", "https://")):
        if requests is None:
            raise ModuleNotFoundError("requests is required to load URL sources")
        response = requests.get(
            input_value,
            timeout=60,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            },
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or input_value.lower().endswith(".pdf"):
            text = read_pdf_bytes(response.content)
            return SourceDocument(
                input_value=input_value,
                source_type="url_pdf",
                source_label=guess_source_label(input_value),
                raw_text=text,
                metadata={"content_type": content_type},
            )

        if BeautifulSoup is None:
            raise ModuleNotFoundError("beautifulsoup4 is required to parse HTML URL sources")
        soup = BeautifulSoup(response.text, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else None
        meta_description = _pick_meta_content(
            soup,
            [
                {"name": "description"},
                {"property": "og:description"},
                {"name": "citation_title"},
            ],
        )
        citation_title = _pick_meta_content(soup, [{"name": "citation_title"}])
        citation_doi = _pick_meta_content(soup, [{"name": "citation_doi"}])
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = soup.get_text("\n", strip=True)
        return SourceDocument(
            input_value=input_value,
            source_type="url_html",
            source_label=citation_title or page_title or guess_source_label(input_value),
            raw_text=text,
            metadata={
                "content_type": content_type,
                "page_title": page_title,
                "meta_description": meta_description,
                "citation_title": citation_title,
                "citation_doi": citation_doi,
            },
        )

    path = Path(input_value).expanduser().resolve()
    if path.suffix.lower() == ".pdf":
        text = read_pdf_bytes(path.read_bytes())
        return SourceDocument(
            input_value=str(path),
            source_type="local_pdf",
            source_label=path.name,
            raw_text=text,
            metadata={"path": str(path)},
        )

    text = path.read_text(encoding="utf-8")
    return SourceDocument(
        input_value=str(path),
        source_type="local_text",
        source_label=path.name,
        raw_text=text,
        metadata={"path": str(path)},
    )


def guess_source_label(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme:
        return parsed.path.rsplit("/", 1)[-1] or parsed.netloc
    return Path(value).name


def _pick_meta_content(soup: BeautifulSoup, selectors: list[dict[str, str]]) -> str | None:
    for selector in selectors:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def clean_text(text: str, max_chars: int = 25000) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", text)
    compact = re.sub(r"[ \t]+", " ", compact)
    return compact[:max_chars]


def normalize_title(title: str) -> str:
    title = WHITESPACE_RE.sub(" ", title).strip()
    title = re.sub(r"\s*\|\s*PubMed.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*-\s*PubMed.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\|\s*Nature.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^Skip to main content\s*", "", title, flags=re.IGNORECASE)
    title = title.strip(" -|")
    return title


def extract_title(text: str, fallback: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    for candidate_key in ("citation_title", "page_title"):
        candidate = metadata.get(candidate_key)
        if candidate and 8 <= len(candidate) <= 260:
            return normalize_title(candidate)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:12]:
        if (
            20 <= len(line) <= 220
            and not DOI_RE.search(line)
            and "clipboard" not in line.lower()
            and "search history" not in line.lower()
            and "skip to main content" not in line.lower()
        ):
            return normalize_title(line)
    return normalize_title(fallback)


def extract_authors(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:20]:
        if "," in line and len(line) < 300 and not line.lower().startswith(("abstract", "introduction")):
            candidates = [part.strip() for part in re.split(r",| and ", line) if part.strip()]
            if 1 < len(candidates) <= 12:
                return candidates
    return []


def extract_authors_from_metadata(text: str, metadata: dict[str, Any] | None = None) -> list[str]:
    metadata = metadata or {}
    if metadata.get("citation_authors"):
        return metadata["citation_authors"]
    return extract_authors(text)


def detect_diagnoses(text_lower: str) -> list[str]:
    found = []
    for label, keywords in DIAGNOSIS_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            found.append(label)
    return expand_diagnosis_hierarchy(found)


def expand_diagnosis_hierarchy(labels: list[str]) -> list[str]:
    expanded = list(labels)
    if any(label in FTD_SPECIFIC_DIAGNOSES for label in labels):
        expanded.append("FTD")
    if any(label in PPA_SPECIFIC_DIAGNOSES for label in labels):
        expanded.append("PPA")
    return dedupe_strings(expanded)


def normalize_diagnosis_label(label: str) -> str:
    value = WHITESPACE_RE.sub(" ", str(label)).strip().lower()
    if not value:
        return ""

    exact_aliases = {
        "alzheimer's disease": "AD",
        "alzheimer disease": "AD",
        "ad": "AD",
        "behavioral variant frontotemporal dementia": "bvFTD",
        "behavioural variant frontotemporal dementia": "bvFTD",
        "behavioral variant ftd": "bvFTD",
        "behavioural variant ftd": "bvFTD",
        "bvftd": "bvFTD",
        "pick's disease": "bvFTD",
        "picks disease": "bvFTD",
        "semantic variant primary progressive aphasia": "svPPA",
        "svppa": "svPPA",
        "semantic dementia": "svPPA",
        "nonfluent variant primary progressive aphasia": "nfvPPA",
        "non-fluent variant primary progressive aphasia": "nfvPPA",
        "agrammatic variant primary progressive aphasia": "nfvPPA",
        "nonfluent/agrammatic variant primary progressive aphasia": "nfvPPA",
        "non-fluent/agrammatic variant primary progressive aphasia": "nfvPPA",
        "progressive nonfluent aphasia": "nfvPPA",
        "progressive non-fluent aphasia": "nfvPPA",
        "pnfa": "nfvPPA",
        "nfvppa": "nfvPPA",
        "logopenic variant primary progressive aphasia": "lvPPA",
        "logopenic progressive aphasia": "lvPPA",
        "lvppa": "lvPPA",
        "lppa": "lvPPA",
        "primary progressive aphasia": "PPA",
        "frontotemporal dementia with amyotrophic lateral sclerosis": "FTD-ALS",
        "frontotemporal dementia and amyotrophic lateral sclerosis": "FTD-ALS",
        "frontotemporal dementia with motor neuron disease": "FTD-ALS",
        "ftd-als": "FTD-ALS",
        "ftd als": "FTD-ALS",
        "ftd-mnd": "FTD-ALS",
        "ftd mnd": "FTD-ALS",
        "als-ftd": "FTD-ALS",
        "als ftd": "FTD-ALS",
        "progressive supranuclear palsy": "PSP",
        "psp": "PSP",
        "corticobasal syndrome": "CBS",
        "corticobasal degeneration": "CBS",
        "cbs": "CBS",
        "cbd": "CBS",
        "frontotemporal dementia": "FTD",
        "frontotemporal degeneration": "FTD",
        "frontotemporal lobar degeneration": "FTD",
        "ftd": "FTD",
        "dementia with lewy bodies": "DLB",
        "lewy body dementia": "DLB",
        "dlb": "DLB",
        "vascular dementia": "VaD",
        "vad": "VaD",
        "mild cognitive impairment": "MCI",
        "mci": "MCI",
        "control": "Control",
        "healthy control": "Control",
        "healthy controls": "Control",
        "dementia": "Dementia",
    }
    if value in exact_aliases:
        return exact_aliases[value]

    if "semantic" in value and "primary progressive aphasia" in value:
        return "svPPA"
    if ("nonfluent" in value or "non-fluent" in value or "agrammatic" in value) and "primary progressive aphasia" in value:
        return "nfvPPA"
    if "logopenic" in value and "primary progressive aphasia" in value:
        return "lvPPA"
    if "behavioral variant" in value and "frontotemporal" in value:
        return "bvFTD"
    if "amyotrophic lateral sclerosis" in value and "frontotemporal" in value:
        return "FTD-ALS"
    if "motor neuron disease" in value and "frontotemporal" in value:
        return "FTD-ALS"

    return WHITESPACE_RE.sub(" ", str(label)).strip()


def normalize_diagnoses(labels: list[str]) -> list[str]:
    normalized = []
    for label in labels:
        canonical = normalize_diagnosis_label(label)
        if canonical:
            normalized.append(canonical)
    return expand_diagnosis_hierarchy(dedupe_strings(normalized))


def normalize_roi_label(label: Any) -> str:
    value = WHITESPACE_RE.sub(" ", str(label)).strip().lower()
    if not value or value == "none":
        return ""

    exact_aliases = {
        "hippocampus": "hippocampus",
        "total_hippocampus": "hippocampus",
        "entorhinal cortex": "entorhinal cortex",
        "entorhinal": "entorhinal cortex",
        "parahippocampal gyrus": "parahippocampal gyrus",
        "parahippocampal": "parahippocampal gyrus",
        "amygdala": "amygdala",
        "medial temporal lobe": "medial temporal lobe",
        "posterior cingulate cortex": "posterior cingulate cortex",
        "inferior parietal cortex": "inferior parietal cortex",
        "temporal cortex": "temporal cortex",
        "superior temporal cortex": "superior temporal cortex",
        "middle temporal cortex": "middle temporal cortex",
        "inferior temporal cortex": "inferior temporal cortex",
        "frontal cortex": "frontal cortex",
        "anterior temporal cortex": "anterior temporal cortex",
        "insula": "insula",
        "anterior cingulate cortex": "anterior cingulate cortex",
        "white matter": "white matter",
    }
    if value in exact_aliases:
        return exact_aliases[value]

    # FreeSurfer hypointensity labels must not collapse into "white matter":
    # "non-WM-hypointensities" is by definition not white matter, and neither
    # label is the FLAIR/T2 white matter hyperintensity that papers report.
    if "hypointensit" in value:
        if NON_WHITE_MATTER_RE.search(value):
            return "non-white-matter hypointensities"
        return "white matter hypointensities"

    # An anatomically qualified white matter label is a different structure from
    # the cerebral white matter papers report: cerebellar white matter must not
    # collapse into "white matter" just because the phrase is a substring.
    if QUALIFIED_WHITE_MATTER_RE.search(value):
        qualified = QUALIFIED_WHITE_MATTER_RE.sub(r"\1 white matter", value)
        qualified = HEMISPHERE_PREFIX_RE.sub("", qualified)
        return qualified.replace("cerebellum", "cerebellar").strip()

    for alias in ROI_ALIAS_MATCH_ORDER:
        if alias in value:
            return ROI_ALIASES[alias]
    return WHITESPACE_RE.sub(" ", str(label)).strip()


def normalize_metric_label(label: Any) -> str:
    value = WHITESPACE_RE.sub(" ", str(label)).strip().lower()
    if not value or value == "none":
        return ""

    exact_aliases = {
        "surface_area": "surface_area",
        "cortical_thickness": "cortical_thickness",
        "roi_volume": "roi_volume",
        "hippocampal_volume": "hippocampal_volume",
        "white_matter_hyperintensity": "white_matter_hyperintensity",
    }
    if value in exact_aliases:
        return exact_aliases[value]

    for alias, canonical in METRIC_ALIASES.items():
        if alias in value:
            return canonical
    return WHITESPACE_RE.sub(" ", str(label)).strip()


def detect_modalities(text_lower: str) -> list[str]:
    found = []
    for label, keywords in MODALITY_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            found.append(label)
    return found


def detect_rois(text_lower: str) -> list[str]:
    return [roi for roi in ROI_KEYWORDS if roi in text_lower]


def detect_symptoms(text_lower: str) -> list[str]:
    found = []
    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            found.append(symptom)
    return found


def detect_sex_scope(text_lower: str) -> list[str]:
    found = []
    if "female" in text_lower or "women" in text_lower:
        found.append("F")
    if "male" in text_lower or "men" in text_lower:
        found.append("M")
    return found


def detect_imaging_metrics(text_lower: str) -> list[str]:
    metrics = []
    if "cortical thickness" in text_lower or "cortical thinning" in text_lower:
        metrics.append("cortical_thickness")
    if "volume" in text_lower or "atrophy" in text_lower:
        metrics.append("roi_volume")
    if "hippocampal volume" in text_lower:
        metrics.append("hippocampal_volume")
    if "white matter hyperintens" in text_lower:
        metrics.append("white_matter_hyperintensity")
    return dedupe_strings(metrics)


def extract_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+", text)
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) > 40]


def heuristic_findings(text: str, rois: list[str]) -> tuple[list[str], list[str]]:
    sentences = extract_sentences(text)
    findings = []
    limitations = []
    for sentence in sentences:
        lower = sentence.lower()
        if any(term in lower for term in ["significant", "associated", "atrophy", "thinning", "preservation", "predict", "accuracy"]):
            if len(findings) < 8:
                findings.append(sentence[:500])
        if any(term in lower for term in ["limitation", "however", "caution", "may not", "not always", "depends on"]):
            if len(limitations) < 5:
                limitations.append(sentence[:500])
    if not findings and rois:
        findings.append(f"Potential ROI evidence detected: {', '.join(rois)}.")
    return findings, limitations


def heuristic_record(doc: SourceDocument) -> LiteratureRecord:
    text = clean_text(doc.raw_text)
    text_lower = text.lower()
    doi_match = DOI_RE.search(text) or (
        re.search(DOI_RE, doc.metadata.get("citation_doi", "")) if doc.metadata.get("citation_doi") else None
    )
    years = [int(match.group()) for match in YEAR_RE.finditer(text[:5000])]
    findings, limitations = heuristic_findings(text, detect_rois(text_lower))
    summary = doc.metadata.get("meta_description") or " ".join(extract_sentences(text)[:3])[:1200] or None
    diagnoses = detect_diagnoses(text_lower)
    modalities = detect_modalities(text_lower)
    rois = detect_rois(text_lower)
    symptoms = detect_symptoms(text_lower)
    sex_scope = detect_sex_scope(text_lower)
    imaging_metrics = detect_imaging_metrics(text_lower)

    if doc.source_type == "url_html" and "pubmed.ncbi.nlm.nih.gov" in doc.input_value:
        modalities = list(dict.fromkeys(modalities + infer_modalities_from_title_or_summary(doc.metadata.get("page_title", ""), summary or "")))

    if doc.source_type == "url_html" and "who.int" in doc.input_value:
        diagnoses = list(dict.fromkeys(diagnoses + ["AD", "VaD", "Control"]))

    return LiteratureRecord(
        source_label=doc.source_label,
        title=extract_title(text, doc.source_label, doc.metadata),
        year=min(years) if years else None,
        doi=doi_match.group(0) if doi_match else None,
        authors=extract_authors_from_metadata(text, doc.metadata),
        study_design=infer_study_design(text_lower),
        population=infer_population(text_lower),
        diagnoses=diagnoses,
        modalities=modalities,
        rois=rois,
        symptoms=symptoms,
        sex_scope=sex_scope,
        imaging_metrics=imaging_metrics,
        findings=findings,
        limitations=limitations,
        abstract_like_summary=summary,
        extraction_mode="heuristic",
        source_type=doc.source_type,
        source_path_or_url=doc.input_value,
    )


def infer_modalities_from_title_or_summary(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    return detect_modalities(text)


def infer_study_design(text_lower: str) -> str | None:
    if "systematic review" in text_lower:
        return "Systematic review"
    if "review" in text_lower:
        return "Review"
    if "cross-sectional" in text_lower:
        return "Cross-sectional"
    if "longitudinal" in text_lower:
        return "Longitudinal"
    if "cohort" in text_lower:
        return "Cohort"
    if "case-control" in text_lower:
        return "Case-control"
    if "randomized" in text_lower:
        return "Randomized"
    return None


def infer_population(text_lower: str) -> str | None:
    for phrase in [
        "patients with mild cognitive impairment",
        "patients with alzheimer",
        "behavioral variant frontotemporal dementia",
        "behavioural variant frontotemporal dementia",
        "semantic variant primary progressive aphasia",
        "nonfluent variant primary progressive aphasia",
        "non-fluent variant primary progressive aphasia",
        "agrammatic variant primary progressive aphasia",
        "logopenic variant primary progressive aphasia",
        "frontotemporal dementia",
        "healthy control",
        "older adults",
        "adni",
    ]:
        if phrase in text_lower:
            return phrase
    return None


def call_openai_compatible_ai(
    text: str,
    source_label: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    prompt = f"""
You are extracting structured literature data for a neuroimaging evidence database.
Return strict JSON with keys:
title, year, doi, authors, study_design, population, diagnoses, modalities, rois, symptoms, findings, limitations, abstract_like_summary.
Diagnoses/modalities/rois/symptoms/authors/findings/limitations must be arrays.
Source label: {source_label}
Text:
\"\"\"{text[:18000]}\"\"\"
""".strip()
    if requests is None:
        raise ModuleNotFoundError("requests is required to call an OpenAI-compatible extraction endpoint")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You extract clean JSON for neuroimaging literature databases."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def detect_openai_compatible_endpoint() -> tuple[str | None, str | None]:
    if requests is None:
        return None, None
    candidates = []
    env_ollama = None
    try:
        import os

        env_ollama = os.environ.get("OLLAMA_HOST")
    except Exception:
        env_ollama = None

    if env_ollama:
        candidates.extend(
            [
                env_ollama.rstrip("/"),
                env_ollama.rstrip("/") + "/v1",
            ]
        )
    candidates.extend(
        [
            "http://127.0.0.1:11434/v1",
            "http://localhost:11434/v1",
            "http://127.0.0.1:11434",
            "http://localhost:11434",
        ]
    )

    for base in candidates:
        probe_url = base.rstrip("/") + ("/models" if base.endswith("/v1") else "/api/tags")
        try:
            response = requests.get(probe_url, timeout=5)
            if response.ok:
                if probe_url.endswith("/models"):
                    data = response.json()
                    models = data.get("data", [])
                    model_id = models[0]["id"] if models else None
                    return base.rstrip("/"), model_id
                data = response.json()
                models = data.get("models", [])
                model_id = models[0]["name"] if models else None
                return base.rstrip("/") + "/v1", model_id
        except Exception:
            continue

    return None, None


def ai_record(
    doc: SourceDocument,
    base_url: str,
    model: str,
    api_key: str | None = None,
) -> LiteratureRecord:
    extracted = call_openai_compatible_ai(
        text=clean_text(doc.raw_text),
        source_label=doc.source_label,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    return LiteratureRecord(
        source_label=doc.source_label,
        title=normalize_title(extracted.get("title") or doc.source_label),
        year=safe_int(extracted.get("year")),
        doi=extracted.get("doi"),
        authors=coerce_list(extracted.get("authors")),
        study_design=extracted.get("study_design"),
        population=extracted.get("population"),
        diagnoses=coerce_list(extracted.get("diagnoses")),
        modalities=coerce_list(extracted.get("modalities")),
        rois=coerce_list(extracted.get("rois")),
        symptoms=coerce_list(extracted.get("symptoms")),
        sex_scope=coerce_list(extracted.get("sex_scope")),
        imaging_metrics=coerce_list(extracted.get("imaging_metrics")),
        findings=coerce_list(extracted.get("findings")),
        limitations=coerce_list(extracted.get("limitations")),
        abstract_like_summary=extracted.get("abstract_like_summary"),
        extraction_mode="ai",
        source_type=doc.source_type,
        source_path_or_url=doc.input_value,
    )


def clean_record(record: LiteratureRecord) -> LiteratureRecord:
    record.title = normalize_title(record.title or record.source_label)
    record.authors = dedupe_strings(record.authors)
    record.diagnoses = normalize_diagnoses(record.diagnoses)
    record.modalities = dedupe_strings(record.modalities)
    record.rois = dedupe_strings(record.rois)
    record.symptoms = dedupe_strings(record.symptoms)
    record.sex_scope = dedupe_strings(record.sex_scope)
    record.imaging_metrics = dedupe_strings(record.imaging_metrics)
    record.findings = dedupe_strings(record.findings)
    record.limitations = dedupe_strings(record.limitations)

    if not record.study_design:
        lower_title = (record.title or "").lower()
        if "freesurfer" in lower_title or "pipeline" in lower_title:
            record.study_design = "Methods / software"
        elif "fact sheet" in lower_title:
            record.study_design = "Public health fact sheet"

    if record.source_path_or_url and "pubmed.ncbi.nlm.nih.gov" in record.source_path_or_url:
        record.source_type = "pubmed"
    elif record.source_path_or_url and "pmc.ncbi.nlm.nih.gov" in record.source_path_or_url:
        record.source_type = "pmc"
    elif record.source_path_or_url and "who.int" in record.source_path_or_url:
        record.source_type = "who_web"

    title_lower = (record.title or "").lower()
    if record.source_type == "who_web":
        record.title = "Dementia"
        record.study_design = "Public health fact sheet"
        record.diagnoses = ["Dementia"]
        record.modalities = []
        record.rois = []
        record.symptoms = [
            "cognitive decline",
            "memory impairment",
            "mood change",
            "behavioural change",
            "functional decline",
        ]
        record.sex_scope = []
        record.imaging_metrics = []

    if title_lower == "freesurfer":
        record.study_design = "Methods / software"
        record.diagnoses = []
        record.modalities = ["MRI"]
        record.imaging_metrics = ["cortical_thickness", "roi_volume"]

    if "fastsurfer" in title_lower:
        record.study_design = "Methods / validation"
        record.modalities = ["MRI"]
        record.imaging_metrics = dedupe_strings(record.imaging_metrics + ["cortical_thickness", "roi_volume"])

    if "neurodesk" in title_lower:
        record.study_design = "Platform / methods"
        record.modalities = ["MRI"]

    return record


def dedupe_strings(values: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for value in values:
        value = WHITESPACE_RE.sub(" ", str(value)).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_evidence_framework(records: list[dict[str, Any]] | list[LiteratureRecord]) -> pd.DataFrame:
    rows = []
    for idx, raw_record in enumerate(records, start=1):
        explicit_paper_code = None
        if isinstance(raw_record, LiteratureRecord):
            record = raw_record
            paper_id = idx
        else:
            paper_id = raw_record.get("paper_id") or idx
            explicit_paper_code = raw_record.get("paper_code")
            record = LiteratureRecord(
                source_label=str(raw_record.get("source_label", "")),
                title=raw_record.get("title"),
                year=safe_int(raw_record.get("year")),
                doi=raw_record.get("doi"),
                authors=coerce_list(raw_record.get("authors")),
                study_design=raw_record.get("study_design"),
                population=raw_record.get("population"),
                diagnoses=normalize_diagnoses(coerce_list(raw_record.get("diagnoses"))),
                modalities=coerce_list(raw_record.get("modalities")),
                rois=dedupe_strings([normalize_roi_label(x) for x in coerce_list(raw_record.get("rois")) if normalize_roi_label(x)]),
                symptoms=coerce_list(raw_record.get("symptoms")),
                sex_scope=coerce_list(raw_record.get("sex_scope")),
                imaging_metrics=dedupe_strings([normalize_metric_label(x) for x in coerce_list(raw_record.get("imaging_metrics")) if normalize_metric_label(x)]),
                findings=coerce_list(raw_record.get("findings")),
                limitations=coerce_list(raw_record.get("limitations")),
                abstract_like_summary=raw_record.get("abstract_like_summary"),
                extraction_mode=raw_record.get("extraction_mode") or "unknown",
                source_type=raw_record.get("source_type"),
                source_path_or_url=raw_record.get("source_path_or_url"),
            )

        paper_code = str(
            explicit_paper_code
            or (f"P{paper_id:03d}" if isinstance(paper_id, int) else paper_id)
        )

        diagnoses = record.diagnoses or [None]
        rois = record.rois or [None]
        metrics = record.imaging_metrics or [None]
        for diagnosis in diagnoses:
            for roi in rois:
                for metric in metrics:
                    rows.append(
                        {
                            "paper_id": paper_id,
                            "paper_code": paper_code,
                            "diagnosis": diagnosis,
                            "diagnosis_normalized": normalize_diagnosis_label(diagnosis) if diagnosis else None,
                            "roi_name": roi,
                            "roi_name_normalized": normalize_roi_label(roi) if roi else None,
                            "imaging_metric": metric,
                            "imaging_metric_normalized": normalize_metric_label(metric) if metric else None,
                            "pattern_summary": " | ".join(record.findings or []),
                            "source_title": record.title,
                            "doi": record.doi,
                            "source_detail_url": record.source_path_or_url,
                            "source_type": record.source_type,
                            "study_design": record.study_design,
                            "modalities": "; ".join(record.modalities or []),
                            "limitations": " | ".join(record.limitations or []),
                            "matching_rule": "exact_normalized_diagnosis_roi_metric",
                            "match_status": "candidate_evidence_match",
                            "manual_review_status": "candidate_requires_manual_review",
                            "evidence_category": "roi_evidence" if roi or metric else "pathology_evidence",
                        }
                    )
    return pd.DataFrame(rows)


def _record_to_dict(record: dict[str, Any] | LiteratureRecord) -> dict[str, Any]:
    return record if isinstance(record, dict) else record.__dict__


def build_pathology_evidence_table(records: list[dict[str, Any]] | list[LiteratureRecord]) -> pd.DataFrame:
    """Build a paper-level disease/pathology evidence view.

    This table is intentionally separate from ROI evidence so that the workflow
    can show whether a paper supports disease/pathology concepts, regional MRI
    findings, or both.
    """
    rows = []
    for paper_id, record in enumerate(records, start=1):
        rec = _record_to_dict(record)
        diagnoses = normalize_diagnoses(coerce_list(rec.get("diagnoses"))) or [None]
        symptoms = coerce_list(rec.get("symptoms"))
        findings = coerce_list(rec.get("findings"))
        evidence_terms = symptoms or findings or [rec.get("abstract_like_summary")]
        for diagnosis in diagnoses:
            for term in evidence_terms:
                if term is None:
                    continue
                rows.append(
                    {
                        "paper_id": paper_id,
                        "paper_code": f"P{paper_id:03d}",
                        "source_title": rec.get("title"),
                        "year": safe_int(rec.get("year")),
                        "doi": rec.get("doi"),
                        "source_detail_url": rec.get("source_path_or_url"),
                        "diagnosis": diagnosis,
                        "diagnosis_normalized": normalize_diagnosis_label(diagnosis) if diagnosis else None,
                        "pathology_or_clinical_feature": str(term),
                        "study_design": rec.get("study_design"),
                        "evidence_category": "pathology_evidence",
                        "note": "Paper-level disease/pathology evidence; does not require an ROI match.",
                    }
                )
    return pd.DataFrame(rows)


def build_roi_evidence_table(records: list[dict[str, Any]] | list[LiteratureRecord]) -> pd.DataFrame:
    """Build a regional imaging evidence view with paper identifiers."""
    evidence = build_evidence_framework(records)
    if evidence.empty:
        return evidence
    roi_cols = [
        "paper_id",
        "paper_code",
        "source_title",
        "doi",
        "source_detail_url",
        "diagnosis",
        "diagnosis_normalized",
        "roi_name",
        "roi_name_normalized",
        "imaging_metric",
        "imaging_metric_normalized",
        "modalities",
        "study_design",
        "pattern_summary",
        "limitations",
    ]
    out = evidence[[c for c in roi_cols if c in evidence.columns]].copy()
    if "evidence_category" not in out.columns:
        out["evidence_category"] = "roi_evidence"
    out["matching_rule"] = "candidate match on normalized diagnosis + ROI + imaging metric"
    out["manual_review_status"] = "candidate_requires_manual_review"
    out["note"] = "ROI-level imaging evidence; paper_code links this row back to the source registry/detail URL."
    return out


def add_structural_table_notes(df: pd.DataFrame) -> pd.DataFrame:
    """Add presentation notes for missing demographics and feature provenance."""
    out = normalize_structural_dataframe(df)
    notes = []
    for _, row in out.iterrows():
        row_notes = []
        if "sex" not in out.columns or pd.isna(row.get("sex")) or str(row.get("sex")).strip().lower() in {"", "unknown", "nan", "none"}:
            row_notes.append("sex unavailable")
        if "age" not in out.columns or pd.isna(row.get("age")):
            row_notes.append("age unavailable")
        if "value_numeric" in out.columns and pd.isna(row.get("value_numeric")):
            row_notes.append("numeric feature value unavailable")
        if "source_pipeline" in out.columns and str(row.get("source_pipeline", "")).strip():
            row_notes.append(f"feature source: {row.get('source_pipeline')}")
        if not row_notes:
            row_notes.append("metadata and numeric feature available")
        notes.append("; ".join(row_notes))
    out["note"] = notes
    return out


METADATA_COMPLETENESS_FIELDS = (
    "subject_id", "diagnosis", "sex", "age", "mmse", "cdr",
    "roi_name", "imaging_metric", "value_numeric", "source_pipeline",
)

ATLAS_TRANSLATION_COMPLETENESS_FIELDS = (
    "subject_id", "source_roi_name", "standard_roi_name", "standard_hemisphere",
    "standard_roi_category", "imaging_metric", "value_numeric", "unit",
    "atlas_name", "atlas_version", "parcellation_method",
    "atlas_translation_rule", "atlas_translation_confidence", "atlas_translation_review_status",
)


def metadata_completeness_report(
    df: pd.DataFrame, fields: tuple[str, ...] = METADATA_COMPLETENESS_FIELDS
) -> pd.DataFrame:
    """Summarize whether fields needed for demographic/group interpretation exist."""
    rows = []
    for column in fields:
        if column in df.columns:
            values = df[column]
            missing = values.isna() | values.astype(str).str.strip().str.lower().isin({"", "unknown", "nan", "none"})
            rows.append(
                {
                    "field": column,
                    "exists": True,
                    "n_rows": len(df),
                    "n_missing_or_unknown": int(missing.sum()),
                    "n_available": int((~missing).sum()),
                    "note": "required for demographic interpretation" if column in {"sex", "age"} else "workflow field",
                }
            )
        else:
            rows.append(
                {
                    "field": column,
                    "exists": False,
                    "n_rows": len(df),
                    "n_missing_or_unknown": len(df),
                    "n_available": 0,
                    "note": "missing field; do not interpret this dimension",
                }
            )
    return pd.DataFrame(rows)


MMC_SHEET_CONFIG = {
    "Surface": {"metric": "surface_area", "unit": "mm2", "observed_cell_label": "OBSERVED SURFACE"},
    "Thickness": {"metric": "cortical_thickness", "unit": "mm", "observed_cell_label": "OBSERVED THICKNESS"},
    "Volume": {"metric": "roi_volume", "unit": "mm3", "observed_cell_label": "OBSERVED VOLUME"},
}


def _load_xlsx_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for item in root.findall("a:si", namespace):
        parts = [
            text_node.text or ""
            for text_node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        strings.append("".join(parts))
    return strings


def _sheet_targets_by_name(zip_file: zipfile.ZipFile) -> dict[str, str]:
    namespace = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    rel_root = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root}
    workbook_root = ET.fromstring(zip_file.read("xl/workbook.xml"))
    targets: dict[str, str] = {}
    for sheet in workbook_root.findall("a:sheets/a:sheet", namespace):
        sheet_name = sheet.attrib["name"]
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rels[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        targets[sheet_name] = target
    return targets


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    formula = cell.find("a:f", namespace)
    if formula is not None:
        return "=" + (formula.text or "")
    value = cell.find("a:v", namespace)
    if value is None:
        return None
    text = value.text or ""
    if cell.attrib.get("t") == "s" and text.isdigit():
        idx = int(text)
        if idx < len(shared_strings):
            return shared_strings[idx]
    return text


def _split_mmc_region_and_hemisphere(region_label: Any) -> tuple[str, str | None]:
    label = WHITESPACE_RE.sub(" ", str(region_label)).strip()
    lower = label.lower()
    hemisphere = None
    if lower.endswith(" l"):
        hemisphere = "lh"
        label = label[:-2].strip()
    elif lower.endswith(" r"):
        hemisphere = "rh"
        label = label[:-2].strip()
    return label, hemisphere


def normalize_mmc_region_label(label: Any) -> str:
    """Normalize MMC/Potvin region names to FreeSurfer-like cortical labels."""
    label, _ = _split_mmc_region_and_hemisphere(label)
    value = WHITESPACE_RE.sub(" ", str(label)).strip().lower()
    replacements = {
        "gyrus": "",
        "cortex": "",
        "lobe": "",
        "lobule": "",
        "-": " ",
        "_": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = WHITESPACE_RE.sub(" ", value).strip()
    compact = value.replace(" ", "")
    aliases = {
        "superiortemporal": "superiortemporal",
        "middletemporal": "middletemporal",
        "inferiortemporal": "inferiortemporal",
        "bankssts": "bankssts",
        "entorhinal": "entorhinal cortex",
        "parahippocampal": "parahippocampal gyrus",
        "fusiform": "fusiform",
        "transversetemporal": "transversetemporal",
        "superiorfrontal": "superiorfrontal",
        "rostralmiddlefrontal": "rostralmiddlefrontal",
        "caudalmiddlefrontal": "caudalmiddlefrontal",
        "parsopercularis": "parsopercularis",
        "parstriangularis": "parstriangularis",
        "parsorbitalis": "parsorbitalis",
        "lateralorbitofrontal": "lateralorbitofrontal",
        "medialorbitofrontal": "medialorbitofrontal",
        "precentral": "precentral",
        "postcentral": "postcentral",
        "superiorparietal": "superiorparietal",
        "inferiorparietal": "inferior parietal cortex",
        "supramarginal": "supramarginal",
        "precuneus": "precuneus",
        "posteriorcingulate": "posterior cingulate cortex",
        "isthmuscingulate": "isthmuscingulate",
        "rostralanteriorcingulate": "rostralanteriorcingulate",
        "caudalanteriorcingulate": "caudalanteriorcingulate",
        "cuneus": "cuneus",
        "lingual": "lingual",
        "pericalcarine": "pericalcarine",
        "lateraloccipital": "lateraloccipital",
    }
    return aliases.get(compact, compact or value)


def _first_meaningful(*values: Any) -> Any:
    """Return the first value that is not None, NaN or blank.

    ``or`` chains cannot express this: ``float("nan")`` is truthy, so a missing
    registry field would win over a usable fallback value.
    """
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


ATLAS_TRANSLATION_STATUS_QUANTITATIVE = "reviewed_quantitative_ready"
ATLAS_TRANSLATION_STATUS_QUALITATIVE = "reviewed_qualitative_only"
ATLAS_TRANSLATION_STATUS_PENDING = "pending_human_review"
# v0.1 of the registry used a single reviewed status. It is kept as an alias so
# older registries keep working, but new registries must use the three tiers.
ATLAS_TRANSLATION_LEGACY_REVIEWED_STATUS = "reviewed_for_pilot"

ATLAS_TRANSLATION_STATUSES = (
    "accepted",
    ATLAS_TRANSLATION_STATUS_QUANTITATIVE,
    ATLAS_TRANSLATION_STATUS_QUALITATIVE,
    ATLAS_TRANSLATION_STATUS_PENDING,
)
ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES = frozenset(
    {ATLAS_TRANSLATION_STATUS_QUANTITATIVE, ATLAS_TRANSLATION_LEGACY_REVIEWED_STATUS}
)
ATLAS_TRANSLATION_QUALITATIVE_STATUSES = frozenset({ATLAS_TRANSLATION_STATUS_QUALITATIVE, "accepted"})

# Backwards-compatible aliases used by earlier code paths.
ATLAS_TRANSLATION_REVIEWED_STATUS = ATLAS_TRANSLATION_LEGACY_REVIEWED_STATUS
ATLAS_TRANSLATION_PENDING_STATUS = ATLAS_TRANSLATION_STATUS_PENDING

ATLAS_TRANSLATION_FALLBACK_RULE = "fallback normalize_roi_label"

# How a standard ROI relates to the source ROI it was mapped from. A paper ROI
# that is broader than one FreeSurfer parcel cannot be equated with that parcel
# numerically, however well the names match.
MAPPING_RELATION_EXACT = "exact"
MAPPING_RELATION_BROADER = "broader_than_source"
MAPPING_RELATION_NARROWER = "narrower_than_source"
MAPPING_RELATION_COMPOSITE = "composite_derived"
MAPPING_RELATION_NOT_COMPARABLE = "not_comparable"
MAPPING_RELATION_UNASSESSED = "unassessed"

MAPPING_RELATIONS = (
    MAPPING_RELATION_EXACT,
    MAPPING_RELATION_BROADER,
    MAPPING_RELATION_NARROWER,
    MAPPING_RELATION_COMPOSITE,
    MAPPING_RELATION_NOT_COMPARABLE,
    MAPPING_RELATION_UNASSESSED,
)
MAPPING_RELATIONS_NUMERIC_ALLOWED = frozenset({MAPPING_RELATION_EXACT})
MAPPING_RELATIONS_QUALITATIVE_ONLY = frozenset(
    {MAPPING_RELATION_BROADER, MAPPING_RELATION_NARROWER, MAPPING_RELATION_COMPOSITE}
)

ATLAS_TRANSLATION_REGISTRY_COLUMNS = (
    "source_atlas_name",
    "source_atlas_code",
    "source_file_pattern",
    "source_roi_name",
    "standard_roi_name",
    "hemisphere",
    "roi_category",
    "mapping_relation",
    "translation_rule",
    "translation_confidence",
    "manual_review_status",
    "reviewer",
    "reviewed_at",
    "reference_url",
    "note",
)


# FreeSurfer writes one stats file per parcellation scheme. The file name is the
# only reliable evidence of which atlas produced a row: lh/rh.aparc.stats is
# Desikan-Killiany, and DKT lives in lh/rh.aparc.DKTatlas.stats.
FREESURFER_ATLAS_BY_STATS_FILE = (
    ("aparc.dktatlas", {
        "atlas_code": "dkt_aparc",
        "atlas_name": "Desikan-Killiany-Tourville (aparc.DKTatlas)",
        "parcellation_method": "FreeSurfer surface-based DKT cortical parcellation",
    }),
    ("aparc.a2009s", {
        "atlas_code": "destrieux_a2009s",
        "atlas_name": "Destrieux (aparc.a2009s)",
        "parcellation_method": "FreeSurfer surface-based Destrieux cortical parcellation",
    }),
    ("aparc", {
        "atlas_code": "dk_aparc",
        "atlas_name": "Desikan-Killiany (aparc)",
        "parcellation_method": "FreeSurfer surface-based Desikan-Killiany cortical parcellation",
    }),
    ("aseg", {
        "atlas_code": "freesurfer_aseg",
        "atlas_name": "FreeSurfer aseg",
        "parcellation_method": "FreeSurfer automated subcortical segmentation",
    }),
)

FREESURFER_ATLAS_CODE_ALIASES = {
    "dkt_aparc": {"dkt", "dktatlas", "desikan-killiany-tourville"},
    "dk_aparc": {"dk", "aparc", "desikan-killiany", "desikan killiany"},
    "destrieux_a2009s": {"destrieux", "a2009s"},
    "freesurfer_aseg": {"aseg", "freesurfer aseg", "subcortical"},
}


def resolve_atlas_from_source_file(source_file: Any) -> dict[str, str | None]:
    """Identify the atlas from the FreeSurfer stats file that produced a row.

    Naming an atlas from anything other than the source file is unsafe: the DK
    and DKT parcellations share ROI names, so a mislabelled ``atlas_name``
    cannot be detected from the ROI column alone.
    """
    name = str(_first_meaningful(source_file) or "").lower()
    for token, atlas in FREESURFER_ATLAS_BY_STATS_FILE:
        if token in name:
            return dict(atlas)
    return {"atlas_code": "unknown_atlas", "atlas_name": None, "parcellation_method": None}


def atlas_code_from_label(label: Any) -> str:
    """Map a free-text atlas label onto a canonical atlas code."""
    text = str(_first_meaningful(label) or "").strip().lower()
    if not text:
        return "unknown_atlas"
    if "dktatlas" in text or "dkt" in text or "tourville" in text:
        return "dkt_aparc"
    if "a2009s" in text or "destrieux" in text:
        return "destrieux_a2009s"
    if "aseg" in text or "subcortical" in text:
        return "freesurfer_aseg"
    if "aparc" in text or "desikan" in text:
        return "dk_aparc"
    return "unknown_atlas"


def check_atlas_naming_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """Flag rows whose declared atlas disagrees with their source stats file.

    This is the check that catches Desikan-Killiany data being described as
    DKT, which no amount of ROI-name inspection would reveal.
    """
    if df.empty or "source_file" not in df.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    columns = [c for c in ["source_file", "atlas_name", "source_atlas_name", "parcellation_method"] if c in df.columns]
    for keys, group in df.groupby(columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(columns, keys))
        resolved = resolve_atlas_from_source_file(record.get("source_file"))
        declared_labels = [record.get("atlas_name"), record.get("source_atlas_name")]
        declared_codes = {atlas_code_from_label(label) for label in declared_labels if _first_meaningful(label)}
        declared_codes.discard("unknown_atlas")
        expected = resolved["atlas_code"]
        if not declared_codes:
            verdict = "atlas_not_declared"
        elif declared_codes == {expected}:
            verdict = "consistent"
        else:
            verdict = "declared_atlas_conflicts_with_source_file"
        rows.append(
            {
                **record,
                "n_rows": len(group),
                "expected_atlas_code": expected,
                "expected_atlas_name": resolved["atlas_name"],
                "declared_atlas_codes": ", ".join(sorted(declared_codes)) or None,
                "consistency": verdict,
            }
        )
    return pd.DataFrame(rows).sort_values("consistency").reset_index(drop=True)


def atlas_translation_evidence_tier(manual_review_status: Any, mapping_relation: Any) -> str:
    """Reduce review status and mapping relation to one evidence tier.

    Numeric comparison needs both a reviewed status and an exact relation. A
    reviewed but broader or composite mapping supports qualitative linking only,
    and nothing promotes a pending mapping.
    """
    status = str(_first_meaningful(manual_review_status) or ATLAS_TRANSLATION_STATUS_PENDING)
    relation = str(_first_meaningful(mapping_relation) or MAPPING_RELATION_UNASSESSED)
    if relation == MAPPING_RELATION_NOT_COMPARABLE:
        return "not_comparable"
    if status in ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES and relation in MAPPING_RELATIONS_NUMERIC_ALLOWED:
        return "quantitative"
    if status in ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES | ATLAS_TRANSLATION_QUALITATIVE_STATUSES:
        return "qualitative"
    return "pending"


def load_atlas_translation_registry(registry_path: str | Path, required: bool = False) -> pd.DataFrame:
    """Load the project ROI/atlas translation registry.

    With ``required=True`` a missing or empty registry raises instead of
    returning an empty frame, because an empty registry silently turns the
    whole translation layer into a no-op.
    """
    path = Path(registry_path)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Atlas translation registry not found: {path}")
        return pd.DataFrame()
    raw_text = path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    metadata: dict[str, Any] = {}
    if isinstance(data, dict):
        metadata = {key: value for key, value in data.items() if key != "mappings"}
        data = data.get("mappings", [])
    if not isinstance(data, list):
        raise ValueError(f"Atlas translation registry must contain a list of mappings: {path}")
    registry = pd.DataFrame(data)
    if registry.empty:
        if required:
            raise ValueError(f"Atlas translation registry contains no mappings: {path}")
        return registry
    for column in ATLAS_TRANSLATION_REGISTRY_COLUMNS:
        if column not in registry.columns:
            registry[column] = None
    registry["source_roi_name_normalized"] = registry["source_roi_name"].map(
        lambda value: WHITESPACE_RE.sub(" ", str(value)).strip().lower()
    )
    registry["standard_roi_name_normalized"] = registry["standard_roi_name"].map(normalize_roi_label)
    registry.attrs["registry_path"] = str(path)
    registry.attrs["registry_sha256"] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    registry.attrs["registry_metadata"] = metadata
    return registry


def atlas_translation_registry_conflicts(registry: pd.DataFrame) -> pd.DataFrame:
    """List registry rows that share a lookup key and would shadow each other."""
    if registry.empty:
        return pd.DataFrame()
    key = ["source_roi_name_normalized", "source_file_pattern"]
    conflicts = registry[registry.duplicated(subset=key, keep=False)]
    if conflicts.empty:
        return pd.DataFrame()
    columns = [
        column
        for column in ["source_atlas_name", "source_file_pattern", "source_roi_name", "standard_roi_name",
                       "hemisphere", "translation_confidence", "manual_review_status"]
        if column in conflicts.columns
    ]
    return conflicts[columns].sort_values(key[:1] + columns[:1]).reset_index(drop=True)


def _atlas_source_matches(pattern: Any, source_file: Any, atlas_name: Any) -> bool:
    if pd.isna(pattern) or str(pattern).strip() in {"", "*"}:
        return True
    pattern_text = str(pattern).strip().lower()
    source_text = f"{source_file or ''} {atlas_name or ''}".lower()
    return pattern_text in source_text


def apply_atlas_translation(
    df: pd.DataFrame,
    registry_path: str | Path = "./workflow_sources/atlas_translation/minimal_atlas_translation.json",
    required_registry: bool = True,
) -> pd.DataFrame:
    """Translate source-specific ROI names into standard ROI labels.

    The translation layer keeps the original ROI and atlas visible, then adds
    auditable standard fields used by downstream patient-to-paper comparison.
    The pre-translation ``roi_name_normalized`` and ``hemisphere`` values are
    kept as ``*_source`` columns so the before/after audit trail survives.
    """
    out = normalize_structural_dataframe(df)
    registry = load_atlas_translation_registry(registry_path, required=required_registry)
    if "source_roi_name" not in out.columns and "roi_name" in out.columns:
        out["source_roi_name"] = out["roi_name"]
    if "source_atlas_name" not in out.columns and "atlas_name" in out.columns:
        out["source_atlas_name"] = out["atlas_name"]

    candidates_by_key: dict[str, list[dict[str, Any]]] = {}
    if not registry.empty:
        for record in registry.to_dict("records"):
            candidates_by_key.setdefault(record["source_roi_name_normalized"], []).append(record)

    translated_rows: list[dict[str, Any]] = []
    for row in out.to_dict("records"):
        source_roi_name = _first_meaningful(row.get("source_roi_name"), row.get("roi_name"))
        source_roi_key = WHITESPACE_RE.sub(" ", str(source_roi_name)).strip().lower()
        source_atlas_name = _first_meaningful(row.get("source_atlas_name"), row.get("atlas_name"))
        matches = [
            candidate
            for candidate in candidates_by_key.get(source_roi_key, [])
            if _atlas_source_matches(
                candidate.get("source_file_pattern"), row.get("source_file"), source_atlas_name
            )
        ]

        translated = dict(row)
        translated["roi_name_normalized_source"] = row.get("roi_name_normalized")
        translated["hemisphere_source"] = row.get("hemisphere")
        translated["atlas_translation_candidate_count"] = len(matches)
        resolved_atlas = resolve_atlas_from_source_file(row.get("source_file"))
        translated["source_atlas_code"] = resolved_atlas["atlas_code"]
        translated["source_atlas_name_from_file"] = resolved_atlas["atlas_name"]
        if matches:
            mapping = matches[0]
            note = _first_meaningful(mapping.get("note"))
            review_status = _first_meaningful(
                mapping.get("manual_review_status"), ATLAS_TRANSLATION_PENDING_STATUS
            )
            if len(matches) > 1:
                shadowed = ", ".join(sorted({str(other.get("standard_roi_name")) for other in matches[1:]}))
                note = (
                    f"{note or ''} Registry conflict: {len(matches)} rows match this source ROI; "
                    f"shadowed standard names: {shadowed}."
                ).strip()
                review_status = ATLAS_TRANSLATION_PENDING_STATUS
            translated.update(
                {
                    "standard_roi_name": mapping.get("standard_roi_name"),
                    "standard_roi_name_normalized": mapping.get("standard_roi_name_normalized"),
                    "standard_hemisphere": _first_meaningful(
                        mapping.get("hemisphere"), row.get("hemisphere")
                    ),
                    "standard_roi_category": _first_meaningful(mapping.get("roi_category"), "unclassified"),
                    "atlas_translation_rule": _first_meaningful(
                        mapping.get("translation_rule"), "exact source ROI name mapping"
                    ),
                    "atlas_translation_confidence": _first_meaningful(
                        mapping.get("translation_confidence"), "manual_review_required"
                    ),
                    "atlas_translation_review_status": review_status,
                    "atlas_translation_note": note,
                    "mapping_relation": _first_meaningful(
                        mapping.get("mapping_relation"), MAPPING_RELATION_UNASSESSED
                    ),
                    "registry_source_atlas_name": mapping.get("source_atlas_name"),
                    "registry_source_atlas_code": _first_meaningful(
                        mapping.get("source_atlas_code"),
                        atlas_code_from_label(mapping.get("source_atlas_name")),
                    ),
                    "atlas_translation_reviewer": mapping.get("reviewer"),
                    "atlas_translation_reviewed_at": mapping.get("reviewed_at"),
                    "atlas_translation_reference_url": mapping.get("reference_url"),
                }
            )
        else:
            translated.update(
                {
                    "standard_roi_name": normalize_roi_label(source_roi_name),
                    "standard_roi_name_normalized": normalize_roi_label(source_roi_name),
                    "standard_hemisphere": row.get("hemisphere"),
                    "standard_roi_category": "unclassified",
                    "atlas_translation_rule": ATLAS_TRANSLATION_FALLBACK_RULE,
                    "atlas_translation_confidence": "low",
                    "atlas_translation_review_status": ATLAS_TRANSLATION_PENDING_STATUS,
                    "atlas_translation_note": "No exact atlas registry row; fallback normalization used.",
                    "mapping_relation": MAPPING_RELATION_UNASSESSED,
                    "registry_source_atlas_name": None,
                    "registry_source_atlas_code": None,
                    "atlas_translation_reviewer": None,
                    "atlas_translation_reviewed_at": None,
                    "atlas_translation_reference_url": None,
                }
            )
        translated["atlas_translation_evidence_tier"] = atlas_translation_evidence_tier(
            translated["atlas_translation_review_status"], translated["mapping_relation"]
        )
        translated["registry_atlas_matches_source_file"] = (
            translated["registry_source_atlas_code"] is None
            or translated["registry_source_atlas_code"] == translated["source_atlas_code"]
        )
        translated_rows.append(translated)

    translated_df = pd.DataFrame(translated_rows)
    if translated_df.empty:
        return translated_df
    if len(translated_df) != len(out):
        raise RuntimeError(
            f"Atlas translation changed the row count: {len(out)} in, {len(translated_df)} out"
        )
    translated_df["roi_name_normalized"] = translated_df["standard_roi_name_normalized"]
    translated_df["hemisphere"] = translated_df["standard_hemisphere"].map(normalize_hemisphere_label)
    translated_df.attrs.update(registry.attrs)
    return translated_df


def atlas_translation_review_gaps(
    translated_df: pd.DataFrame,
    ready_statuses: frozenset[str] = ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES,
) -> pd.DataFrame:
    """List distinct source ROIs that are not cleared for quantitative use.

    Deduplication is on the source ROI itself, not on the full row, so subject
    count and measured values cannot inflate the gap list.
    """
    if translated_df.empty or "atlas_translation_review_status" not in translated_df.columns:
        return pd.DataFrame()
    pending = translated_df[
        ~translated_df["atlas_translation_review_status"].astype(str).isin(ready_statuses)
    ]
    if pending.empty:
        return pd.DataFrame()
    keys = [column for column in ["source_atlas_name", "source_roi_name"] if column in pending.columns]
    # Hemisphere is taken from the source row, not decided by the mapping, so
    # grouping on it would split every cortical ROI into two identical gaps.
    detail = [
        column
        for column in ["standard_roi_name", "standard_roi_category",
                       "atlas_translation_rule", "atlas_translation_confidence",
                       "atlas_translation_review_status", "atlas_translation_note"]
        if column in pending.columns
    ]
    aggregations: dict[str, Any] = {"n_rows": ("source_roi_name", "size")}
    if "standard_hemisphere" in pending.columns:
        aggregations["hemispheres"] = (
            "standard_hemisphere",
            lambda values: ",".join(sorted({str(value) for value in values})),
        )
    if "subject_id" in pending.columns:
        aggregations["n_subjects"] = ("subject_id", lambda values: values.astype(str).nunique())
    return (
        pending.groupby(keys + detail, dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values(["n_rows"] + keys, ascending=[False] + [True] * len(keys))
        .reset_index(drop=True)
    )


def atlas_translation_registry_attribution_gaps(registry_df: pd.DataFrame) -> pd.DataFrame:
    """List mappings that claim a review but do not say who made it or when.

    A review decision without an attributable reviewer and date cannot be
    audited or revisited, so these rows are reported rather than trusted
    silently. Registry v0.1 recorded no attribution at all, and the decisions
    carried forward from it inherit that gap.
    """
    if registry_df.empty:
        return pd.DataFrame()
    reviewed = registry_df[
        registry_df["manual_review_status"].isin(
            ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES | ATLAS_TRANSLATION_QUALITATIVE_STATUSES
        )
    ]
    if reviewed.empty:
        return pd.DataFrame()

    def _missing(column: str) -> pd.Series:
        if column not in reviewed.columns:
            return pd.Series(True, index=reviewed.index)
        return reviewed[column].map(lambda value: _first_meaningful(value) is None)

    missing_reviewer = _missing("reviewer")
    missing_date = _missing("reviewed_at")
    missing_reference = _missing("reference_url")
    gaps = reviewed[missing_reviewer | missing_date]
    if gaps.empty:
        return pd.DataFrame()
    columns = [
        column
        for column in ["source_roi_name", "standard_roi_name", "mapping_relation", "manual_review_status"]
        if column in gaps.columns
    ]
    return (
        gaps[columns]
        .assign(
            missing_reviewer=missing_reviewer.loc[gaps.index].to_numpy(),
            missing_reviewed_at=missing_date.loc[gaps.index].to_numpy(),
            missing_reference_url=missing_reference.loc[gaps.index].to_numpy(),
        )
        .reset_index(drop=True)
    )


ATLAS_TRANSLATION_REVIEW_QUEUE_COLUMNS = (
    # Evidence for the reviewer.
    "source_atlas_name",
    "source_atlas_code",
    "source_file",
    "source_roi_name",
    "proposed_standard_roi_name",
    "hemispheres_in_data",
    "metrics_in_data",
    "units_in_data",
    "roi_category",
    "current_mapping_relation",
    "current_review_status",
    "n_rows",
    "n_subjects",
    "candidate_reference_rois",
    "blocking_reasons",
    # Columns the reviewer fills in.
    "review_decision",
    "reviewer",
    "reviewed_at",
    "reference_url",
    "review_note",
)


def atlas_translation_review_queue(
    translated_df: pd.DataFrame,
    reference_df: pd.DataFrame | None = None,
    gate_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the worksheet a reviewer fills in, one row per source ROI.

    The queue carries the evidence needed to decide - what the data actually
    contains for that ROI, which published ROIs it might correspond to, and why
    the gate currently refuses it - and leaves the decision columns blank. It
    proposes nothing about the outcome: ``review_decision`` is empty so that a
    pending mapping can only be cleared by a person.
    """
    if translated_df.empty:
        return pd.DataFrame(columns=list(ATLAS_TRANSLATION_REVIEW_QUEUE_COLUMNS))

    pending = translated_df[
        ~translated_df["atlas_translation_review_status"].isin(
            ATLAS_TRANSLATION_QUANTITATIVE_READY_STATUSES
        )
    ]
    if pending.empty:
        return pd.DataFrame(columns=list(ATLAS_TRANSLATION_REVIEW_QUEUE_COLUMNS))

    def _joined(values: pd.Series) -> str | None:
        seen = sorted({str(value) for value in values.dropna()})
        return ", ".join(seen) or None

    def _joined_basenames(values: pd.Series) -> str | None:
        # One stats file per subject, so the full paths would repeat per subject.
        seen = sorted({Path(str(value)).name for value in values.dropna()})
        return ", ".join(seen) or None

    grouped = pending.groupby(["source_atlas_name", "roi_name"], dropna=False)
    rows: list[dict[str, Any]] = []
    for (source_atlas_name, source_roi_name), group in grouped:
        standard_name = _joined(group["standard_roi_name"])
        candidates = None
        if reference_df is not None and not reference_df.empty and standard_name:
            keys = {normalize_roi_label(name) for name in group["standard_roi_name"].dropna()}
            matches = reference_df[reference_df["roi_name"].map(normalize_roi_label).isin(keys)]
            candidates = _joined(matches["roi_name"]) if not matches.empty else None

        reasons = None
        if gate_df is not None and not gate_df.empty and "blocking_reasons" in gate_df.columns:
            keys = {normalize_roi_label(name) for name in group["standard_roi_name"].dropna()}
            related = gate_df[gate_df["roi_name"].isin(keys)]
            reasons = _joined(related["blocking_reasons"]) if not related.empty else None

        rows.append(
            {
                "source_atlas_name": source_atlas_name,
                "source_atlas_code": _joined(group.get("source_atlas_code", pd.Series(dtype=object))),
                "source_file": _joined_basenames(group["source_file"]) if "source_file" in group else None,
                "source_roi_name": source_roi_name,
                "proposed_standard_roi_name": standard_name,
                "hemispheres_in_data": _joined(group["hemisphere"]),
                "metrics_in_data": _joined(group["imaging_metric_normalized"]),
                "units_in_data": _joined(group["unit"]) if "unit" in group else None,
                "roi_category": _joined(group["standard_roi_category"]),
                "current_mapping_relation": _joined(
                    group.get("mapping_relation", pd.Series(dtype=object))
                ),
                "current_review_status": _joined(group["atlas_translation_review_status"]),
                "n_rows": len(group),
                "n_subjects": group["subject_id"].nunique() if "subject_id" in group else None,
                "candidate_reference_rois": candidates,
                "blocking_reasons": reasons,
                "review_decision": None,
                "reviewer": None,
                "reviewed_at": None,
                "reference_url": None,
                "review_note": None,
            }
        )
    queue = pd.DataFrame(rows, columns=list(ATLAS_TRANSLATION_REVIEW_QUEUE_COLUMNS))
    return queue.sort_values(
        ["candidate_reference_rois", "source_atlas_name", "source_roi_name"],
        na_position="last",
    ).reset_index(drop=True)


def atlas_translation_unused_registry_rows(
    translated_df: pd.DataFrame, registry: pd.DataFrame
) -> pd.DataFrame:
    """List registry mappings that never matched a row in the input data."""
    if registry.empty:
        return pd.DataFrame()
    if translated_df.empty or "source_roi_name" not in translated_df.columns:
        matched: set[str] = set()
    else:
        translated = translated_df[
            translated_df["atlas_translation_rule"].astype(str).ne(ATLAS_TRANSLATION_FALLBACK_RULE)
        ]
        matched = set(
            translated["source_roi_name"].map(
                lambda value: WHITESPACE_RE.sub(" ", str(value)).strip().lower()
            )
        )
    unused = registry[~registry["source_roi_name_normalized"].isin(matched)]
    columns = [
        column
        for column in ["source_atlas_name", "source_file_pattern", "source_roi_name",
                       "standard_roi_name", "roi_category", "manual_review_status", "note"]
        if column in unused.columns
    ]
    return unused[columns].reset_index(drop=True)


def summarize_atlas_translation(translated_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize translation coverage for presentation and audit."""
    if translated_df.empty:
        return pd.DataFrame()
    group_cols = [
        column
        for column in [
            "source_atlas_name",
            "standard_roi_category",
            "atlas_translation_confidence",
            "atlas_translation_review_status",
        ]
        if column in translated_df.columns
    ]
    if not group_cols:
        return pd.DataFrame()
    return (
        translated_df.groupby(group_cols, dropna=False)
        .agg(
            n_rows=("standard_roi_name", "size"),
            n_unique_source_rois=("source_roi_name", lambda values: values.astype(str).nunique()),
            n_unique_standard_rois=("standard_roi_name", lambda values: values.astype(str).nunique()),
        )
        .reset_index()
        .sort_values("n_rows", ascending=False)
    )


VERSION_UNREPORTED_RE = re.compile(r"not reported|not applicable|unknown|unspecified")
MAPS_PIPELINE_RE = re.compile(r"\bmaps\b|\bstaple\b|boundary shift integral")
VISUAL_RATING_RE = re.compile(r"visual|semiquantitative|rating")
LONGITUDINAL_RE = re.compile(r"annualized|percentage change|atrophy rate|per year")
GLOBAL_VOLUME_RE = re.compile(r"segmented (brain )?volumetry|whole[- ]brain volume")
WHOLE_BRAIN_THICKNESS_RE = re.compile(r"whole[- ]brain.*thickness|mean cortical thickness")


def classify_parcellation_scheme(*texts: Any) -> str:
    """Identify the segmentation routine that produced a value.

    This is finer grained than the pipeline family: FreeSurfer's subcortical
    segmentation and its surface-based cortical parcellation are different
    routines within the same software.
    """
    blob = " ".join(str(text) for text in texts if _first_meaningful(text) is not None).lower()
    if not blob.strip():
        return "unclassified_parcellation"
    if VISUAL_RATING_RE.search(blob) and "freesurfer" not in blob:
        return "visual_rating"
    if "boundary shift integral" in blob or "hbsi" in blob:
        return "boundary_shift_integral"
    if "multiple-atlas" in blob or "multi-atlas" in blob or "staple" in blob or "template library" in blob:
        return "multi_atlas_propagation"
    if "whole-brain mean" in blob or "whole brain mean" in blob or "surface-based morphometry" in blob:
        return "whole_brain_surface_morphometry"
    if "aseg" in blob or "subcortical segmentation" in blob or "medial temporal lobe structures" in blob:
        return "freesurfer_subcortical_segmentation"
    if "aparc" in blob or "desikan" in blob or "cortical parcellation" in blob:
        return "freesurfer_cortical_parcellation"
    if "segmented volumetry" in blob or "segmented brain volumetry" in blob:
        return "study_specific_volumetry"
    return "unclassified_parcellation"


PARCELLATION_SCHEME_FAMILY = {
    "freesurfer_subcortical_segmentation": "freesurfer",
    "freesurfer_cortical_parcellation": "freesurfer",
    "whole_brain_surface_morphometry": "surface_morphometry",
    "multi_atlas_propagation": "multi_atlas",
    "boundary_shift_integral": "multi_atlas",
    "visual_rating": "visual_rating",
    "study_specific_volumetry": "study_specific",
    "unclassified_parcellation": "unclassified",
}


def classify_pipeline_family(*texts: Any) -> str:
    """Group processing descriptions into comparable pipeline families.

    Two measurements of the same anatomical range are still not comparable when
    they come from different segmentation pipelines.
    """
    blob = " ".join(str(text) for text in texts if _first_meaningful(text) is not None).lower()
    if not blob.strip():
        return "unclassified_pipeline"
    if VISUAL_RATING_RE.search(blob) and "freesurfer" not in blob:
        return "visual_rating"
    if MAPS_PIPELINE_RE.search(blob):
        return "maps_multi_atlas"
    if "cat12" in blob or "spm" in blob:
        return "cat12_spm"
    if "freesurfer" in blob:
        return "freesurfer"
    if "study-specific" in blob or "study specific" in blob:
        return "study_specific"
    return "unclassified_pipeline"


def classify_measurement_scope(
    imaging_metric: Any, hemisphere: Any, normalization_method: Any = None
) -> str:
    """Classify what anatomical range and measure a value actually represents.

    ``normalization_method`` is the literature registry's own statement of scope
    (for example "unadjusted total left-plus-right hippocampal volume"), so it
    wins over the metric and hemisphere columns when present.
    """
    method = str(_first_meaningful(normalization_method) or "").lower()
    metric = str(_first_meaningful(imaging_metric) or "").lower()
    side = str(_first_meaningful(hemisphere) or "").lower()

    if LONGITUDINAL_RE.search(method) or "atrophy_rate" in metric or "change" in metric:
        return "longitudinal_rate"
    if VISUAL_RATING_RE.search(method) or "hyperintensity" in metric:
        return "visual_rating_scale"
    if WHOLE_BRAIN_THICKNESS_RE.search(method):
        return "whole_brain_mean_thickness"
    if GLOBAL_VOLUME_RE.search(method):
        return "global_segmented_volume"

    if "thickness" in metric:
        family = "roi_thickness"
    elif "volume" in metric or "area" in metric:
        family = "roi_volume" if "area" not in metric else "roi_surface_area"
    else:
        return "unknown_scope"

    if side == "bilateral" or "left-plus-right" in method or method.startswith("bilateral"):
        return f"{family}_bilateral"
    if side in {"lh", "rh"}:
        return f"{family}_unilateral"
    return f"{family}_unspecified_laterality"


def _scope_verdict(patient_scope: str, reference_scope: str) -> str:
    if patient_scope == reference_scope:
        return "scope_match"
    if reference_scope == "longitudinal_rate":
        return "patient_single_timepoint_cannot_supply_rate"
    if reference_scope == "visual_rating_scale":
        return "different_measurement_modality"
    if reference_scope in {"whole_brain_mean_thickness", "global_segmented_volume"}:
        return "global_reference_scope_vs_regional_patient_roi"
    patient_family, _, patient_laterality = patient_scope.rpartition("_")
    reference_family, _, reference_laterality = reference_scope.rpartition("_")
    if patient_family != reference_family:
        return "metric_family_mismatch"
    # Laterality is directional. A per-hemisphere patient value can be summed
    # into a bilateral one, but a bilateral value cannot be split back apart,
    # and in that direction the per-hemisphere patient row already exists.
    if patient_laterality == "unilateral" and reference_laterality == "bilateral":
        return "patient_requires_bilateral_aggregation"
    if patient_laterality == "bilateral" and reference_laterality == "unilateral":
        return "reference_is_unilateral_use_per_hemisphere_patient_row"
    return "laterality_unspecified"


def classify_version_reporting(*texts: Any) -> str:
    blob = " ".join(str(text) for text in texts if _first_meaningful(text) is not None).lower()
    if not blob.strip():
        return "version_unreported"
    if "study-specific" in blob or "study specific" in blob:
        return "study_specific_template"
    if VERSION_UNREPORTED_RE.search(blob):
        return "version_unreported"
    return "version_reported"


BILATERAL_AGGREGATION_RULES = {
    "roi_volume": "sum",
    "hippocampal_volume": "sum",
    "surface_area": "sum",
    "cortical_thickness": "mean",
}


def aggregate_bilateral_rois(
    translated_df: pd.DataFrame,
    group_cols: tuple[str, ...] = (
        "subject_id",
        "standard_roi_name",
        "imaging_metric_normalized",
        "unit",
    ),
) -> pd.DataFrame:
    """Combine left and right rows into bilateral rows.

    Most published group statistics are bilateral while FreeSurfer output is
    per hemisphere, so ROI name translation on its own cannot make the two
    comparable. Volumes and areas are summed, thickness is averaged, and the
    unavailability of surface-area weights is recorded rather than hidden.
    """
    if translated_df.empty:
        return pd.DataFrame()
    required = {"hemisphere", "value_numeric", "imaging_metric_normalized"}
    missing = required - set(translated_df.columns)
    if missing:
        raise ValueError(f"aggregate_bilateral_rois requires columns: {sorted(missing)}")

    keys = [column for column in group_cols if column in translated_df.columns]
    paired = translated_df[translated_df["hemisphere"].astype(str).isin({"lh", "rh"})]
    if paired.empty:
        return pd.DataFrame()

    carry_cols = [
        column
        for column in ["diagnosis", "diagnosis_normalized", "sex", "age", "mmse", "cdr",
                       "standard_roi_category", "source_atlas_name", "atlas_name", "atlas_version",
                       "parcellation_method", "source_pipeline", "source_atlas_code",
                       "atlas_translation_confidence", "atlas_translation_review_status",
                       "mapping_relation", "atlas_translation_evidence_tier"]
        if column in paired.columns
    ]

    rows: list[dict[str, Any]] = []
    for key_values, group in paired.groupby(keys, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        hemispheres = sorted(set(group["hemisphere"].astype(str)))
        metric = str(group["imaging_metric_normalized"].iloc[0])
        rule = BILATERAL_AGGREGATION_RULES.get(metric)
        values = pd.to_numeric(group["value_numeric"], errors="coerce")

        if rule == "sum":
            value = values.sum(min_count=1)
            method = "sum of left and right"
        elif rule == "mean":
            value = values.mean()
            method = "unweighted mean of left and right; surface-area weights unavailable"
        else:
            value = None
            method = f"no bilateral aggregation rule for metric {metric!r}"

        if rule is None:
            status = "no_rule_for_metric"
        elif len(hemispheres) != 2:
            status = "incomplete_hemisphere_coverage"
        elif pd.isna(value):
            status = "no_numeric_value"
        else:
            status = "aggregated"

        record = dict(zip(keys, key_values))
        record.update(
            {
                "hemisphere": "bilateral",
                "value_numeric": value,
                "n_source_rows": len(group),
                "hemispheres_present": ",".join(hemispheres),
                "bilateral_aggregation_method": method,
                "bilateral_aggregation_status": status,
            }
        )
        for column in carry_cols:
            uniques = group[column].astype(str).unique()
            record[column] = group[column].iloc[0] if len(uniques) == 1 else "mixed"
        rows.append(record)
    return pd.DataFrame(rows).sort_values(keys).reset_index(drop=True)


UNIT_SYNONYMS = {
    "mm3": "mm3", "mm^3": "mm3", "mm³": "mm3", "cubic mm": "mm3",
    "cubic millimeter": "mm3", "cubic millimeters": "mm3",
    "mm2": "mm2", "mm^2": "mm2", "mm²": "mm2",
    "mm": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm3": "cm3", "cm^3": "cm3", "cm³": "cm3", "ml": "cm3", "milliliter": "cm3", "milliliters": "cm3",
    "%": "percent", "percent": "percent",
    "%/year": "percent_per_year", "percent/year": "percent_per_year", "% per year": "percent_per_year",
    "mm3/year": "mm3_per_year", "mm^3/year": "mm3_per_year",
    "z-score": "z_score", "z score": "z_score",
    "score": "score", "rating": "score", "ratio": "ratio", "unitless": "unitless",
}


def normalize_unit_label(unit: Any) -> str | None:
    """Canonicalize unit spellings without merging different scales.

    ``mm^3`` and ``mm3`` are the same unit and are merged; ``mm3`` and ``cm3``
    are not, because treating them as equal would silently accept a
    thousand-fold error.
    """
    text = str(_first_meaningful(unit) or "").strip().lower()
    if not text:
        return None
    return UNIT_SYNONYMS.get(text, text)


METRIC_FAMILIES = {
    "roi_volume": "volume",
    "hippocampal_volume": "volume",
    "brain_volume": "volume",
    "cortical_thickness": "thickness",
    "surface_area": "area",
    "visual_rating": "ordinal_rating",
    "atrophy_rating": "ordinal_rating",
    "annualized_atrophy_rate": "volume_change_rate",
    "white_matter_hyperintensity": "wmh_burden",
}


def classify_metric_family(*texts: Any) -> str:
    """Group metric labels into the families that may be compared with each other.

    A rate of change is its own family: an annualized atrophy rate is not a
    volume, so pairing it with a single-timepoint volume must be named as a
    metric mismatch rather than left unclassified.
    """
    for text in texts:
        value = _first_meaningful(text)
        if value is None:
            continue
        normalized = normalize_metric_label(value)
        if normalized in METRIC_FAMILIES:
            return METRIC_FAMILIES[normalized]
        blob = str(value).lower()
        if "rate" in blob or "annualiz" in blob or "annualis" in blob:
            return "volume_change_rate"
        if "hyperintensit" in blob:
            return "wmh_burden"
        if "thick" in blob:
            return "thickness"
        if "volum" in blob or "hippocampal" in blob:
            return "volume"
        if "area" in blob:
            return "area"
        if "rating" in blob or "score" in blob or "scale" in blob:
            return "ordinal_rating"
    return "unclassified_metric"


LONGITUDINAL_RE = re.compile(r"annual|per year|/year|rate of|change|atrophy rate|longitudinal|slope")


def classify_measurement_design(*texts: Any) -> str:
    """Distinguish a cross-sectional value from a rate of change."""
    blob = " ".join(str(text) for text in texts if _first_meaningful(text) is not None).lower()
    if LONGITUDINAL_RE.search(blob):
        return "longitudinal_rate"
    return "cross_sectional"


# The eight checks run for every patient-ROI/reference pairing. Only
# ``software_version`` is advisory: a paper that never states its FreeSurfer
# version is less certain, not incomparable.
DEFINITION_GATE_CHECKS = (
    "roi_definition",
    "atlas_parcellation",
    "hemisphere",
    "metric",
    "unit",
    "processing_pipeline",
    "software_version",
    "measurement_design",
)
DEFINITION_GATE_ADVISORY_CHECKS = frozenset({"software_version"})

# Hemisphere verdicts that pass but say the pairing needs a different patient row.
DEFINITION_GATE_HEMISPHERE_REMEDIES = {
    "patient_requires_bilateral_aggregation": "comparable_after_bilateral_aggregation",
    "reference_is_unilateral_use_per_hemisphere_patient_row": "comparable_via_per_hemisphere_row",
}


def _check_roi_definition(patient_row: Mapping[str, Any]) -> tuple[str, str | None]:
    """Judge whether the patient ROI's own definition is settled.

    A reviewed mapping whose standard ROI is broader than the source parcel is
    the case this check exists for: a paper reporting "medial temporal lobe"
    must not be equated with a single hippocampus value however well the names
    match, so such a pairing is blocked for numeric use and left for
    qualitative interpretation.
    """
    relation = str(_first_meaningful(patient_row.get("mapping_relation")) or MAPPING_RELATION_UNASSESSED)
    status = str(
        _first_meaningful(patient_row.get("atlas_translation_review_status"))
        or ATLAS_TRANSLATION_STATUS_PENDING
    )
    tier = atlas_translation_evidence_tier(status, relation)
    if tier == "quantitative":
        return "reviewed_exact_correspondence", None
    if tier == "not_comparable":
        return "mapping_marked_not_comparable", (
            f"registry records no defensible correspondence for this source ROI "
            f"(mapping_relation={relation})"
        )
    if tier == "qualitative":
        return f"reviewed_{relation}_qualitative_only", (
            f"standard ROI relates to the source ROI as {relation!r}, so the two do not "
            f"denote the same extent; usable for qualitative literature linking only"
        )
    return "pending_human_review", (
        f"source ROI mapping is not yet confirmed by a reviewer "
        f"(status={status}, mapping_relation={relation})"
    )


def _check_atlas_parcellation(patient_scheme: str, reference_scheme: str) -> tuple[str, str | None]:
    """Judge whether the two values came from comparable parcellation schemes."""
    patient_family = PARCELLATION_SCHEME_FAMILY.get(patient_scheme, "unclassified")
    reference_family = PARCELLATION_SCHEME_FAMILY.get(reference_scheme, "unclassified")
    if "unclassified" in (patient_family, reference_family):
        return "parcellation_not_reported", (
            f"parcellation scheme not reported on at least one side "
            f"(patient={patient_scheme}, reference={reference_scheme})"
        )
    if patient_scheme == reference_scheme:
        return "same_parcellation_scheme", None
    if patient_family == reference_family:
        # Different routines of the same software, e.g. FreeSurfer's subcortical
        # segmentation versus its surface-based cortical parcellation.
        return "same_atlas_family_different_scheme", None
    return "different_atlas_family", (
        f"parcellation schemes are from different families "
        f"(patient={patient_scheme}, reference={reference_scheme})"
    )


def _check_hemisphere(patient_hemisphere: Any, reference_hemisphere: Any) -> tuple[str, str | None]:
    """Judge laterality, which fails asymmetrically.

    A per-hemisphere patient value can be aggregated up to a bilateral
    reference, but a bilateral patient value cannot be split to meet a
    unilateral reference; in that direction the per-hemisphere patient row is
    the one to use.
    """
    patient = normalize_hemisphere_label(patient_hemisphere)
    reference = normalize_hemisphere_label(reference_hemisphere)
    if patient is None or reference is None:
        return "hemisphere_not_reported", (
            f"hemisphere missing on at least one side (patient={patient}, reference={reference})"
        )
    if patient == reference:
        return ("both_bilateral" if patient == "bilateral" else "same_hemisphere"), None
    if patient in {"lh", "rh"} and reference == "bilateral":
        return "patient_requires_bilateral_aggregation", None
    if patient == "bilateral" and reference in {"lh", "rh"}:
        return "reference_is_unilateral_use_per_hemisphere_patient_row", None
    return "opposite_hemisphere", (
        f"patient value is {patient} but the reference reports {reference}"
    )


def _check_metric(patient_family: str, reference_family: str) -> tuple[str, str | None]:
    """Judge whether the two quantities are the same kind of measurement."""
    if "unclassified_metric" in (patient_family, reference_family):
        return "metric_not_classified", (
            f"metric could not be classified (patient={patient_family}, reference={reference_family})"
        )
    if patient_family == reference_family:
        return "same_metric_family", None
    return "metric_family_mismatch", (
        f"patient reports {patient_family} but the reference reports {reference_family}"
    )


def _check_unit(patient_unit: Any, reference_unit: Any) -> tuple[str, str | None]:
    """Judge unit equality, which never has a remedy short of conversion."""
    patient = normalize_unit_label(patient_unit)
    reference = normalize_unit_label(reference_unit)
    if patient is None or reference is None:
        return "unit_not_reported", (
            f"unit missing on at least one side (patient={patient_unit!r}, reference={reference_unit!r})"
        )
    if patient == reference:
        return "same_unit", None
    return "unit_mismatch", f"patient unit is {patient!r} but the reference unit is {reference!r}"


def _check_processing_pipeline(patient_family: str, reference_family: str) -> tuple[str, str | None]:
    """Judge whether comparable software produced the two values."""
    if "unclassified_pipeline" in (patient_family, reference_family):
        return "pipeline_not_reported", (
            f"processing pipeline not reported on at least one side "
            f"(patient={patient_family}, reference={reference_family})"
        )
    if patient_family == reference_family:
        return "same_pipeline_family", None
    return "different_pipeline_family", (
        f"patient pipeline is {patient_family} but the reference used {reference_family}"
    )


def _check_software_version(patient_version: str, reference_version: str) -> tuple[str, str | None]:
    """Judge version reporting. Advisory: it downgrades but never blocks."""
    if patient_version == "version_reported" and reference_version == "version_reported":
        return "both_versions_reported", None
    return f"reference_{reference_version}", (
        f"software or atlas version not fully reported "
        f"(patient={patient_version}, reference={reference_version})"
    )


def _check_measurement_design(patient_design: str, reference_design: str) -> tuple[str, str | None]:
    """Judge a cross-sectional value against a rate of change."""
    if patient_design == reference_design:
        return f"both_{patient_design}", None
    if reference_design == "longitudinal_rate":
        return "reference_longitudinal_patient_cross_sectional", (
            "reference reports a longitudinal rate of change while the patient has a "
            "single timepoint measurement"
        )
    return "reference_cross_sectional_patient_longitudinal", (
        "patient value is a rate of change while the reference is cross-sectional"
    )


# Pairings that should actually be used for a quantitative comparison.
DEFINITION_GATE_COMPARABLE_STATES = frozenset(
    {"comparable", "comparable_version_unreported", "comparable_after_bilateral_aggregation"}
)

# Pairings that show the reference is usable for this ROI even though this
# particular pairing is redundant, because the right patient row exists
# elsewhere in the table. Used when cross-checking against the registry's
# row-level curated flag, not for selecting evidence.
DEFINITION_GATE_REFERENCE_USABLE_STATES = DEFINITION_GATE_COMPARABLE_STATES | {
    "comparable_via_per_hemisphere_row"
}


def assess_definition_compatibility(
    patient_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    subject_id: str | None = None,
) -> pd.DataFrame:
    """Decide, per patient-ROI and reference pair, whether the two are comparable.

    Eight properties are checked independently and reported one by one, because
    they fail for different reasons and carry different remedies: the ROI's own
    anatomical definition, the atlas/parcellation, the hemisphere, the metric,
    the unit, the processing pipeline, the software version, and whether the
    value is cross-sectional or a rate of change.

    Every failing check contributes a specific reason to ``blocking_reasons``,
    so a blocked pairing says which property disagreed rather than only that
    something did. Version reporting is advisory: a paper that never states its
    version is less certain, not incomparable.
    """
    if patient_df.empty or reference_df.empty:
        return pd.DataFrame()

    patient = patient_df.copy()
    if subject_id is not None and "subject_id" in patient.columns:
        patient = patient[patient["subject_id"].astype(str).eq(str(subject_id))]
    if patient.empty:
        return pd.DataFrame()

    patient_roi_col = "standard_roi_name" if "standard_roi_name" in patient.columns else "roi_name_normalized"
    patient["_roi_key"] = patient[patient_roi_col].map(normalize_roi_label)

    refs = reference_df.copy()
    refs["_roi_key"] = refs["roi_name"].map(normalize_roi_label)
    refs["_hemisphere"] = refs["hemisphere"].map(normalize_hemisphere_label)
    refs["_metric"] = refs["imaging_metric"].map(normalize_metric_label)

    rows: list[dict[str, Any]] = []
    for _, patient_row in patient.iterrows():
        patient_scope = classify_measurement_scope(
            patient_row.get("imaging_metric_normalized"), patient_row.get("hemisphere")
        )
        patient_family = classify_pipeline_family(
            patient_row.get("source_pipeline"),
            patient_row.get("parcellation_method"),
            patient_row.get("atlas_name"),
        )
        patient_version = classify_version_reporting(patient_row.get("atlas_version"))
        patient_scheme = classify_parcellation_scheme(
            patient_row.get("parcellation_method"),
            patient_row.get("atlas_name"),
            patient_row.get("source_atlas_code"),
            patient_row.get("source_file"),
        )
        patient_metric_family = classify_metric_family(
            patient_row.get("imaging_metric_normalized"), patient_row.get("imaging_metric")
        )
        patient_design = classify_measurement_design(
            patient_row.get("statistic_type"), patient_row.get("imaging_metric_normalized")
        )
        roi_definition_verdict, roi_definition_reason = _check_roi_definition(patient_row)
        candidates = refs[refs["_roi_key"].eq(patient_row["_roi_key"])]

        for _, ref in candidates.iterrows():
            reference_scope = classify_measurement_scope(
                ref["_metric"], ref["_hemisphere"], ref.get("normalization_method")
            )
            reference_family = classify_pipeline_family(
                ref.get("processing_pipeline"),
                ref.get("processing_software"),
                ref.get("parcellation_method"),
            )
            reference_version = classify_version_reporting(
                ref.get("atlas_version"), ref.get("processing_software_version")
            )

            reference_scheme = classify_parcellation_scheme(
                ref.get("parcellation_method"),
                ref.get("atlas_name"),
                ref.get("processing_pipeline"),
            )
            reference_metric_family = classify_metric_family(ref["_metric"], ref.get("imaging_metric"))
            reference_design = classify_measurement_design(
                ref.get("normalization_method"), ref.get("statistic_type"), ref["_metric"], ref.get("unit")
            )

            checks: dict[str, tuple[str, str | None]] = {
                "roi_definition": (roi_definition_verdict, roi_definition_reason),
                "atlas_parcellation": _check_atlas_parcellation(patient_scheme, reference_scheme),
                "hemisphere": _check_hemisphere(patient_row.get("hemisphere"), ref["_hemisphere"]),
                "metric": _check_metric(patient_metric_family, reference_metric_family),
                "unit": _check_unit(patient_row.get("unit"), ref.get("unit")),
                "processing_pipeline": _check_processing_pipeline(patient_family, reference_family),
                "software_version": _check_software_version(patient_version, reference_version),
                "measurement_design": _check_measurement_design(patient_design, reference_design),
            }

            hemisphere_verdict = checks["hemisphere"][0]
            blocking_checks = [
                name
                for name in DEFINITION_GATE_CHECKS
                if name not in DEFINITION_GATE_ADVISORY_CHECKS
                and checks[name][1] is not None
                and not (name == "hemisphere" and hemisphere_verdict in DEFINITION_GATE_HEMISPHERE_REMEDIES)
            ]
            blocking_reasons = [f"{name}: {checks[name][1]}" for name in blocking_checks]

            version_verdict = checks["software_version"][0]
            if blocking_checks:
                gate = "not_comparable"
            elif hemisphere_verdict in DEFINITION_GATE_HEMISPHERE_REMEDIES:
                gate = DEFINITION_GATE_HEMISPHERE_REMEDIES[hemisphere_verdict]
            elif version_verdict == "both_versions_reported":
                gate = "comparable"
            else:
                gate = "comparable_version_unreported"

            scope_verdict = _scope_verdict(patient_scope, reference_scope)
            pipeline_verdict = checks["processing_pipeline"][0]
            blocking_axis = ",".join(blocking_checks) or None

            rows.append(
                {
                    **{f"check_{name}": checks[name][0] for name in DEFINITION_GATE_CHECKS},
                    "blocking_checks": blocking_axis,
                    "blocking_reasons": " | ".join(blocking_reasons) or None,
                    "n_blocking_checks": len(blocking_checks),
                    "patient_parcellation_scheme": patient_scheme,
                    "reference_parcellation_scheme": reference_scheme,
                    "patient_metric_family": patient_metric_family,
                    "reference_metric_family": reference_metric_family,
                    "patient_measurement_design": patient_design,
                    "reference_measurement_design": reference_design,
                    "patient_mapping_relation": _first_meaningful(
                        patient_row.get("mapping_relation"), MAPPING_RELATION_UNASSESSED
                    ),
                    "patient_review_status": _first_meaningful(
                        patient_row.get("atlas_translation_review_status"),
                        ATLAS_TRANSLATION_STATUS_PENDING,
                    ),
                    "subject_id": patient_row.get("subject_id"),
                    "roi_name": patient_row["_roi_key"],
                    "imaging_metric": patient_row.get("imaging_metric_normalized"),
                    "patient_hemisphere": patient_row.get("hemisphere"),
                    "patient_value": patient_row.get("value_numeric"),
                    "patient_unit": patient_row.get("unit"),
                    "patient_scope": patient_scope,
                    "patient_pipeline_family": patient_family,
                    "patient_version_reporting": patient_version,
                    "reference_id": ref.get("reference_id"),
                    "paper_code": ref.get("paper_code"),
                    "source_title": ref.get("source_title"),
                    "reference_diagnosis": ref.get("diagnosis"),
                    "reference_hemisphere": ref["_hemisphere"],
                    "reference_unit": ref.get("unit"),
                    "reference_normalization_method": ref.get("normalization_method"),
                    "reference_scope": reference_scope,
                    "reference_pipeline_family": reference_family,
                    "reference_version_reporting": reference_version,
                    "scope_verdict": scope_verdict,
                    "pipeline_verdict": pipeline_verdict,
                    "version_verdict": version_verdict,
                    "definition_gate": gate,
                    "blocking_axis": blocking_axis,
                    "unit_matches": checks["unit"][0] == "same_unit",
                    "curated_comparison_compatible": ref.get("comparison_compatible"),
                    "curated_atlas_compatibility_status": ref.get("atlas_compatibility_status"),
                }
            )
    return pd.DataFrame(rows)


def summarize_definition_gate(gate_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize gate outcomes and name the checks that blocked each group."""
    if gate_df.empty:
        return pd.DataFrame()
    return (
        gate_df.groupby(["definition_gate", "blocking_checks", "blocking_reasons"], dropna=False)
        .agg(
            n_pairs=("reference_id", "size"),
            n_references=("reference_id", lambda values: values.astype(str).nunique()),
            n_rois=("roi_name", lambda values: values.astype(str).nunique()),
        )
        .reset_index()
        .sort_values("n_pairs", ascending=False)
        .reset_index(drop=True)
    )


def definition_gate_check_report(gate_df: pd.DataFrame) -> pd.DataFrame:
    """Report every check separately: its verdicts and how often it blocked.

    Reading the gate one check at a time is what makes a refusal actionable; a
    single overall verdict cannot say whether the unit, the hemisphere or the
    ROI definition was the problem.
    """
    if gate_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for name in DEFINITION_GATE_CHECKS:
        column = f"check_{name}"
        if column not in gate_df.columns:
            continue
        blocked = gate_df["blocking_checks"].fillna("").str.split(",").map(lambda names: name in names)
        for verdict, group in gate_df.groupby(column, dropna=False):
            rows.append(
                {
                    "check": name,
                    "is_advisory": name in DEFINITION_GATE_ADVISORY_CHECKS,
                    "verdict": verdict,
                    "n_pairs": len(group),
                    "n_pairs_blocked_here": int(blocked.loc[group.index].sum()),
                }
            )
    report = pd.DataFrame(rows)
    order = {name: index for index, name in enumerate(DEFINITION_GATE_CHECKS)}
    return (
        report.assign(_order=report["check"].map(order))
        .sort_values(["_order", "n_pairs"], ascending=[True, False])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def cross_check_definition_gate(gate_df: pd.DataFrame) -> pd.DataFrame:
    """Compare the computed gate against the registry's curated verdict.

    The registry's ``comparison_compatible`` flag is a property of a reference
    row, not of a pairing, so it cannot speak about a patient measure the
    reference never reports. Pairings that fail only because the wrong patient
    row was paired with the reference - a different metric, or the opposite
    hemisphere when the matching hemisphere row exists elsewhere in the table -
    are therefore excluded rather than counted as disagreements.
    """
    if gate_df.empty or "curated_comparison_compatible" not in gate_df.columns:
        return pd.DataFrame()
    wrong_patient_metric = gate_df["scope_verdict"].eq("metric_family_mismatch")
    wrong_patient_hemisphere = gate_df["check_hemisphere"].eq("opposite_hemisphere") & gate_df[
        "blocking_checks"
    ].eq("hemisphere")
    scoped = gate_df[~(wrong_patient_metric | wrong_patient_hemisphere)]
    if scoped.empty:
        return pd.DataFrame()
    computed = scoped["definition_gate"].isin(DEFINITION_GATE_REFERENCE_USABLE_STATES)
    curated = scoped["curated_comparison_compatible"].astype("boolean").fillna(False).astype(bool)
    summary = (
        pd.DataFrame(
            {
                "computed_comparable": computed,
                "curated_comparable": curated,
                "agrees": computed == curated,
                "reference_id": scoped["reference_id"],
                "blocking_axis": scoped["blocking_axis"],
            }
        )
        .groupby(["computed_comparable", "curated_comparable", "agrees", "blocking_axis"], dropna=False)
        .agg(n_pairs=("reference_id", "size"),
             references=("reference_id", lambda values: ", ".join(sorted(set(values.astype(str))))))
        .reset_index()
        .sort_values("n_pairs", ascending=False)
        .reset_index(drop=True)
    )
    summary.attrs["n_pairs_compared"] = int(len(scoped))
    summary.attrs["n_pairs_excluded_wrong_patient_metric"] = int(wrong_patient_metric.sum())
    summary.attrs["n_pairs_excluded_wrong_patient_hemisphere"] = int(wrong_patient_hemisphere.sum())
    return summary


def inspect_mmc_calculator_workbook(mmc_workbook_path: str | Path) -> pd.DataFrame:
    """List MMC/Potvin calculator ROI slots without executing workbook macros."""
    path = Path(mmc_workbook_path)
    if not path.exists():
        return pd.DataFrame(
            [{
                "mmc_workbook_path": str(path),
                "mmc_ready_status": "workbook_not_found",
                "note": "Upload or place mmc1.xlsm in this path before external normative validation.",
            }]
        )

    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as workbook_zip:
        shared_strings = _load_xlsx_shared_strings(workbook_zip)
        targets = _sheet_targets_by_name(workbook_zip)
        namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for sheet_name, config in MMC_SHEET_CONFIG.items():
            if sheet_name not in targets:
                rows.append(
                    {
                        "mmc_workbook_path": str(path),
                        "mmc_sheet": sheet_name,
                        "mmc_ready_status": "sheet_not_found",
                    }
                )
                continue
            sheet_root = ET.fromstring(workbook_zip.read(targets[sheet_name]))
            cells = {
                cell.attrib.get("r"): _xlsx_cell_value(cell, shared_strings)
                for cell in sheet_root.findall(".//a:sheetData/a:row/a:c", namespace)
            }
            title = cells.get("A1")
            for coord, value in cells.items():
                if not coord or not coord.startswith("A") or value is None:
                    continue
                try:
                    row_number = int(coord[1:])
                except ValueError:
                    continue
                if row_number < 12:
                    continue
                label = str(value).strip()
                if not label or label.startswith("="):
                    continue
                region_name, hemisphere = _split_mmc_region_and_hemisphere(label)
                if hemisphere is None:
                    continue
                rows.append(
                    {
                        "mmc_workbook_path": str(path),
                        "mmc_workbook_title": title,
                        "mmc_sheet": sheet_name,
                        "mmc_metric": config["metric"],
                        "mmc_unit": config["unit"],
                        "mmc_region": region_name,
                        "mmc_region_normalized": normalize_mmc_region_label(label),
                        "hemisphere": hemisphere,
                        "mmc_observed_value_cell": f"{sheet_name}!B{row_number}",
                        "mmc_predicted_value_cell": f"{sheet_name}!C{row_number}",
                        "mmc_lower_95pi_cell": f"{sheet_name}!D{row_number}",
                        "mmc_upper_95pi_cell": f"{sheet_name}!E{row_number}",
                        "mmc_zop_cell": f"{sheet_name}!I{row_number}",
                        "mmc_percentile_cell": f"{sheet_name}!L{row_number}",
                        "mmc_ready_status": "roi_slot_available",
                    }
                )
    return pd.DataFrame(rows)


def _patient_covariate_summary(patient: pd.DataFrame) -> dict[str, Any]:
    if patient.empty:
        return {}
    first = patient.iloc[0]
    columns = set(patient.columns)
    tiv_candidates = [
        "estimated_total_intracranial_volume",
        "etiv",
        "eTIV",
        "intracranial_volume",
        "tiv",
    ]
    tiv_value = None
    for column in tiv_candidates:
        if column in columns and patient[column].notna().any():
            tiv_value = patient[column].dropna().iloc[0]
            break
    scanner_field = first.get("scanner_field_strength") if "scanner_field_strength" in columns else None
    scanner_manufacturer = first.get("scanner_manufacturer") if "scanner_manufacturer" in columns else None
    sex = first.get("sex") if "sex" in columns else None
    age = first.get("age") if "age" in columns else None
    return {
        "age": age,
        "sex": sex,
        "estimated_total_intracranial_volume": tiv_value,
        "scanner_field_strength": scanner_field,
        "scanner_manufacturer": scanner_manufacturer,
    }


def build_mmc_cross_validation_table(
    structural_df: pd.DataFrame,
    mmc_workbook_path: str | Path,
    subject_id: str | None = None,
) -> pd.DataFrame:
    """Prepare a transparent bridge from FreeSurfer rows to the MMC/Potvin workbook.

    This function does not execute Excel macros. It shows which patient values can
    be entered into MMC, whether the required covariates are present, and whether
    the atlas family appears compatible with the calculator.
    """
    mmc_slots = inspect_mmc_calculator_workbook(mmc_workbook_path)
    if mmc_slots.empty or "mmc_region_normalized" not in mmc_slots.columns:
        return mmc_slots

    structural = normalize_structural_dataframe(structural_df)
    if subject_id is not None and "subject_id" in structural.columns:
        structural = structural[structural["subject_id"].astype(str).eq(str(subject_id))]
    if structural.empty:
        return pd.DataFrame(
            [{
                "subject_id": subject_id,
                "mmc_workbook_path": str(mmc_workbook_path),
                "mmc_ready_status": "subject_not_found",
            }]
        )

    structural = structural.copy()
    structural["mmc_region_normalized"] = structural["roi_name"].map(normalize_mmc_region_label)
    covariates = _patient_covariate_summary(structural)
    required_covariates = {
        "age": covariates.get("age"),
        "sex": covariates.get("sex"),
        "estimated_total_intracranial_volume": covariates.get("estimated_total_intracranial_volume"),
        "scanner_field_strength": covariates.get("scanner_field_strength"),
        "scanner_manufacturer": covariates.get("scanner_manufacturer"),
    }
    missing_covariates = [
        key
        for key, value in required_covariates.items()
        if pd.isna(value) or str(value).strip().lower() in {"", "nan", "none", "unknown"}
    ]

    rows: list[dict[str, Any]] = []
    for _, slot in mmc_slots.iterrows():
        match = structural[
            structural["mmc_region_normalized"].eq(slot["mmc_region_normalized"])
            & structural["hemisphere"].eq(slot["hemisphere"])
            & structural["imaging_metric_normalized"].eq(slot["mmc_metric"])
            & structural["unit"].astype(str).str.lower().eq(str(slot["mmc_unit"]).lower())
        ]
        if match.empty:
            rows.append(
                {
                    **slot.to_dict(),
                    "subject_id": subject_id,
                    "patient_value": pd.NA,
                    "patient_feature_status": "matching_feature_not_found",
                    "mmc_ready_status": "missing_patient_roi_value",
                    "missing_covariates": ", ".join(missing_covariates),
                    **required_covariates,
                }
            )
            continue
        patient_row = match.iloc[0]
        atlas_name = str(patient_row.get("atlas_name", ""))
        atlas_status = (
            "compatible_desikan_killiany"
            if "desikan-killiany (" in atlas_name.lower() or atlas_name.lower().endswith("(aparc) atlas")
            else "review_required_dkt_vs_desikan_killiany"
            if "dkt" in atlas_name.lower() or "tourville" in atlas_name.lower()
            else "review_required"
        )
        ready = (
            "ready_for_manual_mmc_entry"
            if not missing_covariates and atlas_status == "compatible_desikan_killiany"
            else "not_ready_missing_covariates_or_atlas_review"
        )
        rows.append(
            {
                **slot.to_dict(),
                "subject_id": patient_row.get("subject_id"),
                "patient_roi_name": patient_row.get("roi_name"),
                "patient_value": patient_row.get("value_numeric"),
                "patient_unit": patient_row.get("unit"),
                "patient_atlas_name": patient_row.get("atlas_name"),
                "patient_processing_software": patient_row.get("processing_software"),
                "patient_processing_software_version": patient_row.get("processing_software_version"),
                "patient_feature_status": "matching_feature_found",
                "atlas_compatibility_status": atlas_status,
                "missing_covariates": ", ".join(missing_covariates),
                "mmc_ready_status": ready,
                "manual_action": "Enter patient covariates in F6:J6 and observed values in the listed B-column cells, then record MMC output values.",
                **required_covariates,
            }
        )
    return pd.DataFrame(rows)


def compare_patient_to_mmc_export(
    structural_df: pd.DataFrame,
    mmc_export_df: pd.DataFrame,
    subject_id: str,
) -> pd.DataFrame:
    """Compare patient values with manually exported MMC/Potvin results.

    Expected MMC export columns include: mmc_sheet, mmc_region, hemisphere,
    observed_value, predicted_value, lower_95_prediction_interval,
    upper_95_prediction_interval, zop, percentile.
    """
    structural = normalize_structural_dataframe(structural_df)
    patient = structural[structural["subject_id"].astype(str).eq(str(subject_id))].copy()
    if patient.empty:
        return pd.DataFrame()
    export = mmc_export_df.copy()
    export["mmc_region_normalized"] = export["mmc_region"].map(normalize_mmc_region_label)
    metric_by_sheet = {sheet: config["metric"] for sheet, config in MMC_SHEET_CONFIG.items()}
    export["imaging_metric_normalized"] = export["mmc_sheet"].map(metric_by_sheet)
    patient["mmc_region_normalized"] = patient["roi_name"].map(normalize_mmc_region_label)
    rows = []
    for _, mmc_row in export.iterrows():
        match = patient[
            patient["mmc_region_normalized"].eq(mmc_row["mmc_region_normalized"])
            & patient["hemisphere"].eq(normalize_hemisphere_label(mmc_row.get("hemisphere")))
            & patient["imaging_metric_normalized"].eq(mmc_row["imaging_metric_normalized"])
        ]
        patient_value = pd.NA if match.empty else match.iloc[0].get("value_numeric")
        lower = pd.to_numeric(pd.Series([mmc_row.get("lower_95_prediction_interval")]), errors="coerce").iloc[0]
        upper = pd.to_numeric(pd.Series([mmc_row.get("upper_95_prediction_interval")]), errors="coerce").iloc[0]
        observed = pd.to_numeric(pd.Series([mmc_row.get("observed_value", patient_value)]), errors="coerce").iloc[0]
        if pd.notna(observed) and pd.notna(lower) and pd.notna(upper):
            status = "below_age_adjusted_range" if observed < lower else "above_age_adjusted_range" if observed > upper else "within_age_adjusted_range"
        else:
            status = "mmc_interval_unavailable"
        rows.append(
            {
                "subject_id": subject_id,
                "mmc_sheet": mmc_row.get("mmc_sheet"),
                "roi_name": mmc_row.get("mmc_region"),
                "hemisphere": normalize_hemisphere_label(mmc_row.get("hemisphere")),
                "imaging_metric": mmc_row.get("imaging_metric_normalized"),
                "patient_value_from_workflow": patient_value,
                "observed_value_in_mmc": observed,
                "mmc_predicted_value": mmc_row.get("predicted_value"),
                "mmc_lower_95_prediction_interval": lower,
                "mmc_upper_95_prediction_interval": upper,
                "mmc_zop": mmc_row.get("zop"),
                "mmc_percentile": mmc_row.get("percentile"),
                "mmc_cross_validation_status": status,
                "source_reference": "Potvin normative morphometric calculator / mmc1.xlsm",
            }
        )
    return pd.DataFrame(rows)


def _metadata_value(metadata: dict[str, Any] | None, key: str) -> Any:
    if not metadata:
        return None
    return metadata.get(key)


def parse_freesurfer_aseg_stats(
    stats_path: str | Path,
    subject_id: str,
    diagnosis: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse FreeSurfer aseg.stats into the vertical feature-table format."""
    path = Path(stats_path)
    if not path.exists():
        return []

    estimated_total_intracranial_volume = None
    for comment_line in path.read_text(errors="ignore").splitlines():
        if "EstimatedTotalIntraCranialVol" not in comment_line:
            continue
        numeric_values = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", comment_line)
        if numeric_values:
            estimated_total_intracranial_volume = float(numeric_values[-1])
            break

    rows: list[dict[str, Any]] = []
    for line in path.read_text(errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            value_numeric = float(parts[3])
        except ValueError:
            continue
        structure_name = parts[4]
        structure_lower = structure_name.lower()
        inferred_hemisphere = (
            "lh" if structure_lower.startswith(("left-", "left_", "lh_"))
            else "rh" if structure_lower.startswith(("right-", "right_", "rh_"))
            else None
        )
        rows.append(
            {
                "subject_id": subject_id,
                "diagnosis": diagnosis,
                "sex": _metadata_value(metadata, "sex"),
                "age": _metadata_value(metadata, "age"),
                "mmse": _metadata_value(metadata, "mmse"),
                "cdr": _metadata_value(metadata, "cdr"),
                "roi_name": structure_name,
                "imaging_metric": "roi_volume",
                "value_numeric": value_numeric,
                "unit": "mm3",
                "source_pipeline": "FreeSurfer",
                "atlas_name": "FreeSurfer aseg",
                "atlas_version": "not encoded in aseg.stats",
                "processing_software": "FreeSurfer",
                "processing_software_version": "8.2.0",
                "parcellation_method": "FreeSurfer automated subcortical segmentation",
                "source_file": str(path),
                "data_level": "subject",
                "statistic_type": "raw_measure",
                "hemisphere": inferred_hemisphere,
                "estimated_total_intracranial_volume": estimated_total_intracranial_volume,
            }
        )
    return rows


def parse_freesurfer_aparc_stats(
    stats_path: str | Path,
    subject_id: str,
    diagnosis: str | None = None,
    hemisphere: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse FreeSurfer aparc.stats cortical volume/thickness rows."""
    path = Path(stats_path)
    if not path.exists():
        return []

    filename = path.name.lower()
    if "dktatlas" in filename:
        atlas_name = "Desikan-Killiany-Tourville (DKT) Atlas"
        atlas_version = "FreeSurfer DKTatlas; exact classifier version not encoded in stats file"
        parcellation_method = "FreeSurfer surface-based DKT cortical parcellation"
    elif "a2009s" in filename:
        atlas_name = "Destrieux (aparc.a2009s) Atlas"
        atlas_version = "not encoded in aparc.a2009s.stats"
        parcellation_method = "FreeSurfer surface-based Destrieux cortical parcellation"
    else:
        atlas_name = "Desikan-Killiany (aparc) Atlas"
        atlas_version = "not encoded in aparc.stats"
        parcellation_method = "FreeSurfer surface-based Desikan-Killiany cortical parcellation"

    rows: list[dict[str, Any]] = []
    for line in path.read_text(errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        roi_name = parts[0]
        metric_positions = {
            "surface_area": 2,
            "roi_volume": 3,
            "cortical_thickness": 4,
        }
        for metric_name, position in metric_positions.items():
            try:
                value_numeric = float(parts[position])
            except (IndexError, ValueError):
                continue
            rows.append(
                {
                    "subject_id": subject_id,
                    "diagnosis": diagnosis,
                    "sex": _metadata_value(metadata, "sex"),
                    "age": _metadata_value(metadata, "age"),
                    "mmse": _metadata_value(metadata, "mmse"),
                    "cdr": _metadata_value(metadata, "cdr"),
                    "roi_name": roi_name,
                    "imaging_metric": metric_name,
                    "value_numeric": value_numeric,
                    "unit": "mm2" if metric_name == "surface_area" else "mm3" if metric_name == "roi_volume" else "mm",
                    "source_pipeline": "FreeSurfer",
                    "atlas_name": atlas_name,
                    "atlas_version": atlas_version,
                    "processing_software": "FreeSurfer",
                    "processing_software_version": "8.2.0",
                    "parcellation_method": parcellation_method,
                    "source_file": str(path),
                    "data_level": "subject",
                    "statistic_type": "raw_measure",
                    "hemisphere": hemisphere,
                }
            )
    return rows


def extract_features_from_freesurfer_subject(
    subject_dir: str | Path,
    subject_id: str | None = None,
    diagnosis: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Extract a vertical ROI feature table from one FreeSurfer subject folder.

    Expected input folder:
    ``<SUBJECTS_DIR>/<subject_id>/stats``

    Parsed by default:
    - ``aseg.stats`` for subcortical/whole-brain volume rows
    - ``lh/rh.aparc.DKTatlas.stats`` for DKT cortical volume/thickness rows
      when available, otherwise ``lh/rh.aparc.stats`` (Desikan-Killiany)
    """
    subject_path = Path(subject_dir)
    sid = subject_id or subject_path.name
    stats_dir = subject_path / "stats"
    rows: list[dict[str, Any]] = []
    rows.extend(parse_freesurfer_aseg_stats(stats_dir / "aseg.stats", sid, diagnosis=diagnosis, metadata=metadata))
    for hemisphere in ("lh", "rh"):
        dkt_path = stats_dir / f"{hemisphere}.aparc.DKTatlas.stats"
        aparc_path = stats_dir / f"{hemisphere}.aparc.stats"
        cortical_path = dkt_path if dkt_path.exists() else aparc_path
        rows.extend(
            parse_freesurfer_aparc_stats(
                cortical_path,
                sid,
                diagnosis=diagnosis,
                hemisphere=hemisphere,
                metadata=metadata,
            )
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return add_structural_table_notes(normalize_structural_dataframe(out))


def write_freesurfer_vertical_csv(
    subject_dirs: list[str | Path],
    output_csv_path: str | Path,
    diagnosis_by_subject: dict[str, str] | None = None,
    metadata_by_subject: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Extract FreeSurfer features for multiple subjects and save one CSV."""
    frames = []
    for subject_dir in subject_dirs:
        subject_path = Path(subject_dir)
        subject_id = subject_path.name
        frames.append(
            extract_features_from_freesurfer_subject(
                subject_path,
                subject_id=subject_id,
                diagnosis=(diagnosis_by_subject or {}).get(subject_id),
                metadata=(metadata_by_subject or {}).get(subject_id),
            )
        )
    out = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    output_path = Path(output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    return out


def normalize_structural_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "diagnosis" in out.columns:
        out["diagnosis_normalized"] = out["diagnosis"].apply(normalize_diagnosis_label)
    if "roi_name" in out.columns:
        out["roi_name_normalized"] = out["roi_name"].apply(normalize_roi_label)
    if "imaging_metric" in out.columns:
        out["imaging_metric_normalized"] = out["imaging_metric"].apply(normalize_metric_label)
    if "value_numeric" in out.columns:
        out["value_numeric"] = pd.to_numeric(out["value_numeric"], errors="coerce")
    if "hemisphere" not in out.columns:
        out["hemisphere"] = None
    out["hemisphere"] = out["hemisphere"].astype("object")
    if "roi_name" in out.columns:
        inferred_hemisphere = out["roi_name"].astype(str).str.lower().map(
            lambda value: "lh" if value.startswith(("left-", "left_", "lh_"))
            else "rh" if value.startswith(("right-", "right_", "rh_"))
            else None
        )
        missing_hemisphere = out["hemisphere"].isna() | out["hemisphere"].astype(str).str.lower().isin({"", "none", "nan"})
        out.loc[missing_hemisphere, "hemisphere"] = inferred_hemisphere[missing_hemisphere]
    out["hemisphere"] = out["hemisphere"].map(normalize_hemisphere_label)
    if "unit" not in out.columns:
        out["unit"] = None
    out["unit"] = out["unit"].astype("object")
    if "imaging_metric_normalized" in out.columns:
        inferred_unit = out["imaging_metric_normalized"].map(
            {"roi_volume": "mm3", "hippocampal_volume": "mm3", "cortical_thickness": "mm", "surface_area": "mm2"}
        )
        missing_unit = out["unit"].isna() | out["unit"].astype(str).str.lower().isin({"", "none", "nan"})
        out.loc[missing_unit, "unit"] = inferred_unit[missing_unit]
    return out


def normalize_hemisphere_label(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "left": "lh", "l": "lh", "lh": "lh",
        "right": "rh", "r": "rh", "rh": "rh",
        "both": "bilateral", "bilateral": "bilateral", "whole": "bilateral",
    }
    return aliases.get(normalized, normalized or None)


def query_structural_features(
    df: pd.DataFrame,
    subject_id: str | None = None,
    diagnosis: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
    sex: str | None = None,
    source_pipeline: str | None = None,
) -> pd.DataFrame:
    out = normalize_structural_dataframe(df)
    if subject_id is not None and "subject_id" in out.columns:
        out = out[out["subject_id"].astype(str) == str(subject_id)]
    if diagnosis is not None and "diagnosis_normalized" in out.columns:
        out = out[out["diagnosis_normalized"].astype(str).str.lower() == normalize_diagnosis_label(diagnosis).lower()]
    if roi is not None and "roi_name_normalized" in out.columns:
        out = out[out["roi_name_normalized"].astype(str).str.lower() == normalize_roi_label(roi).lower()]
    if metric is not None and "imaging_metric_normalized" in out.columns:
        out = out[out["imaging_metric_normalized"].astype(str).str.lower() == normalize_metric_label(metric).lower()]
    if sex is not None and "sex" in out.columns:
        out = out[out["sex"].astype(str).str.lower() == sex.lower()]
    if source_pipeline is not None and "source_pipeline" in out.columns:
        out = out[out["source_pipeline"].astype(str).str.lower() == source_pipeline.lower()]
    return out.reset_index(drop=True)


def summarize_structural_features(df: pd.DataFrame, group_cols: tuple[str, ...] = ("diagnosis_normalized", "roi_name_normalized", "imaging_metric_normalized")) -> pd.DataFrame:
    out = normalize_structural_dataframe(df)
    needed = [c for c in group_cols if c in out.columns]
    if not needed:
        return out
    return (
        out.groupby(needed, dropna=False)
        .agg(
            n_rows=("value_numeric", "size"),
            n_non_missing=("value_numeric", lambda x: x.notna().sum()),
            mean_value=("value_numeric", "mean"),
            std_value=("value_numeric", "std"),
        )
        .reset_index()
    )


def query_literature(
    records: list[dict[str, Any]] | list[LiteratureRecord],
    disease: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
    modality: str | None = None,
    source_type: str | None = None,
    title_contains: str | None = None,
) -> pd.DataFrame:
    rows = []
    disease_norm = normalize_diagnosis_label(disease) if disease else None
    roi_norm = normalize_roi_label(roi) if roi else None
    metric_norm = normalize_metric_label(metric) if metric else None

    for rec in records:
        diagnoses = normalize_diagnoses(coerce_list(rec.diagnoses if isinstance(rec, LiteratureRecord) else rec.get("diagnoses")))
        rois = [normalize_roi_label(x) for x in coerce_list(rec.rois if isinstance(rec, LiteratureRecord) else rec.get("rois"))]
        metrics = [normalize_metric_label(x) for x in coerce_list(rec.imaging_metrics if isinstance(rec, LiteratureRecord) else rec.get("imaging_metrics"))]
        modalities = coerce_list(rec.modalities if isinstance(rec, LiteratureRecord) else rec.get("modalities"))
        rec_source_type = rec.source_type if isinstance(rec, LiteratureRecord) else rec.get("source_type")
        rec_title = rec.title if isinstance(rec, LiteratureRecord) else rec.get("title")
        if disease_norm and disease_norm not in diagnoses:
            continue
        if roi_norm and roi_norm not in rois:
            continue
        if metric_norm and metric_norm not in metrics:
            continue
        if modality and not any(str(x).lower() == modality.lower() for x in modalities):
            continue
        if source_type and str(rec_source_type or "").lower() != source_type.lower():
            continue
        if title_contains and title_contains.lower() not in str(rec_title or "").lower():
            continue
        rows.append(rec if isinstance(rec, dict) else rec.__dict__)
    return pd.DataFrame(rows)


def literature_features_for_disease(records: list[dict[str, Any]] | list[LiteratureRecord], disease: str) -> pd.DataFrame:
    disease_norm = normalize_diagnosis_label(disease)
    rows = []
    for rec in records:
        rec_dict = rec if isinstance(rec, dict) else rec.__dict__
        diagnoses = normalize_diagnoses(coerce_list(rec_dict.get("diagnoses")))
        if disease_norm not in diagnoses:
            continue
        for roi in rec_dict.get("rois") or [None]:
            for metric in rec_dict.get("imaging_metrics") or [None]:
                rows.append(
                    {
                        "disease": disease_norm,
                        "title": rec_dict.get("title"),
                        "roi": normalize_roi_label(roi) if roi else None,
                        "metric": normalize_metric_label(metric) if metric else None,
                        "modalities": "; ".join(coerce_list(rec_dict.get("modalities"))),
                        "findings": " | ".join(coerce_list(rec_dict.get("findings"))),
                    }
                )
    return pd.DataFrame(rows)


def literature_diseases_for_features(records: list[dict[str, Any]] | list[LiteratureRecord], features: list[str]) -> pd.DataFrame:
    normalized_features = {normalize_roi_label(f) or normalize_metric_label(f) or str(f).strip().lower() for f in features}
    rows = []
    for rec in records:
        rec_dict = rec if isinstance(rec, dict) else rec.__dict__
        combined = {
            normalize_roi_label(v) for v in coerce_list(rec_dict.get("rois")) if normalize_roi_label(v)
        } | {
            normalize_metric_label(v) for v in coerce_list(rec_dict.get("imaging_metrics")) if normalize_metric_label(v)
        } | {
            str(v).strip().lower() for v in coerce_list(rec_dict.get("symptoms")) if str(v).strip()
        }
        if normalized_features & combined:
            rows.append(
                {
                    "title": rec_dict.get("title"),
                    "diagnoses": "; ".join(normalize_diagnoses(coerce_list(rec_dict.get("diagnoses")))),
                    "matched_features": ", ".join(sorted(normalized_features & combined)),
                    "findings": " | ".join(coerce_list(rec_dict.get("findings"))),
                }
            )
    return pd.DataFrame(rows)


def infer_evidence_direction(pattern_summary: Any) -> str:
    """Return a conservative direction label from a paper's extracted finding text."""
    text = str(pattern_summary or "").lower()
    if any(term in text for term in ["atrophy", "thinning", "reduced", "decreased", "smaller", "lower", "loss"]):
        return "decrease_or_atrophy_reported"
    if any(term in text for term in ["increased", "greater", "larger", "higher"]):
        return "increase_reported"
    if "asymmetr" in text:
        return "asymmetry_reported"
    if any(term in text for term in ["associated", "association", "predict", "correlat"]):
        return "association_reported"
    return "direction_not_extracted"


def compare_features_to_literature(
    structural_df: pd.DataFrame,
    evidence_df: pd.DataFrame,
    diagnosis: str | None = None,
    subject_id: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
) -> pd.DataFrame:
    # Select the patient by subject/feature first. A requested diagnosis filters
    # paper evidence below; it must not hide a patient whose broad clinical label
    # (for example, Dementia) differs from a paper's specific label (AD or FTD).
    patient_rows = query_structural_features(structural_df, subject_id=subject_id, roi=roi, metric=metric)
    if patient_rows.empty:
        return pd.DataFrame()

    evidence = evidence_df.copy()
    if "diagnosis_normalized" not in evidence.columns and "diagnosis" in evidence.columns:
        evidence["diagnosis_normalized"] = evidence["diagnosis"].apply(normalize_diagnosis_label)
    if "roi_name_normalized" not in evidence.columns and "roi_name" in evidence.columns:
        evidence["roi_name_normalized"] = evidence["roi_name"].apply(normalize_roi_label)
    if "imaging_metric_normalized" not in evidence.columns and "imaging_metric" in evidence.columns:
        evidence["imaging_metric_normalized"] = evidence["imaging_metric"].apply(normalize_metric_label)

    merged_rows = []
    for _, row in patient_rows.iterrows():
        matches = evidence.copy()
        patient_diagnosis = row.get("diagnosis_normalized")
        if diagnosis is not None:
            matches = matches[matches["diagnosis_normalized"].astype(str).str.lower() == normalize_diagnosis_label(diagnosis).lower()]
        if pd.notna(row.get("roi_name_normalized")):
            matches = matches[matches["roi_name_normalized"].astype(str).str.lower() == str(row["roi_name_normalized"]).lower()]
        if pd.notna(row.get("imaging_metric_normalized")):
            matches = matches[matches["imaging_metric_normalized"].astype(str).str.lower() == str(row["imaging_metric_normalized"]).lower()]

        if matches.empty:
            merged_rows.append(
                {
                    "subject_id": row.get("subject_id"),
                    "patient_diagnosis": patient_diagnosis,
                    "sex": row.get("sex"),
                    "age": row.get("age"),
                    "mmse": row.get("mmse"),
                    "cdr": row.get("cdr"),
                    "roi_name": row.get("roi_name_normalized"),
                    "imaging_metric": row.get("imaging_metric_normalized"),
                    "value_numeric": row.get("value_numeric"),
                    "evidence_match": False,
                    "matching_rule": "exact_normalized_roi_metric; optional paper diagnosis filter",
                    "match_status": "no_candidate_match",
                    "manual_review_status": "no_candidate_to_review",
                    "paper_id": None,
                    "paper_code": None,
                    "paper_diagnosis": None,
                    "diagnosis_match": None,
                    "source_title": None,
                    "doi": None,
                    "pattern_summary": None,
                    "evidence_direction": None,
                    "quantitative_comparison_possible": False,
                    "patient_value_interpretation": "No paper row with the same normalized ROI and imaging metric.",
                    "limitations": None,
                }
            )
            continue

        for _, match in matches.iterrows():
            paper_diagnosis = match.get("diagnosis_normalized")
            diagnosis_match = bool(
                pd.notna(patient_diagnosis)
                and pd.notna(paper_diagnosis)
                and str(patient_diagnosis).lower() == str(paper_diagnosis).lower()
            )
            reference_mean = pd.to_numeric(pd.Series([match.get("reference_mean")]), errors="coerce").iloc[0]
            reference_std = pd.to_numeric(pd.Series([match.get("reference_std")]), errors="coerce").iloc[0]
            patient_value = pd.to_numeric(pd.Series([row.get("value_numeric")]), errors="coerce").iloc[0]
            quantitative_possible = bool(
                pd.notna(patient_value)
                and pd.notna(reference_mean)
                and pd.notna(reference_std)
                and reference_std != 0
            )
            if quantitative_possible:
                patient_interpretation = (
                    f"z_like_difference={(patient_value - reference_mean) / reference_std:.3f}"
                )
            else:
                patient_interpretation = (
                    "Qualitative feature-to-paper comparison only; the paper evidence row has no harmonized "
                    "reference mean/SD and units for this patient value."
                )
            merged_rows.append(
                {
                    "subject_id": row.get("subject_id"),
                    "patient_diagnosis": patient_diagnosis,
                    "sex": row.get("sex"),
                    "age": row.get("age"),
                    "mmse": row.get("mmse"),
                    "cdr": row.get("cdr"),
                    "roi_name": row.get("roi_name_normalized"),
                    "imaging_metric": row.get("imaging_metric_normalized"),
                    "value_numeric": row.get("value_numeric"),
                    "evidence_match": True,
                    "matching_rule": "exact_normalized_roi_metric; diagnosis reported separately",
                    "match_status": "candidate_evidence_match",
                    "manual_review_status": "candidate_requires_manual_review",
                    "paper_id": match.get("paper_id"),
                    "paper_code": match.get("paper_code"),
                    "paper_diagnosis": paper_diagnosis,
                    "diagnosis_match": diagnosis_match,
                    "source_title": match.get("source_title"),
                    "doi": match.get("doi"),
                    "pattern_summary": match.get("pattern_summary"),
                    "evidence_direction": infer_evidence_direction(match.get("pattern_summary")),
                    "reference_mean": reference_mean,
                    "reference_std": reference_std,
                    "quantitative_comparison_possible": quantitative_possible,
                    "patient_value_interpretation": patient_interpretation,
                    "limitations": match.get("limitations"),
                }
            )
    return pd.DataFrame(merged_rows)


def compare_to_normative_reference(
    structural_df: pd.DataFrame,
    normative_df: pd.DataFrame | None,
    diagnosis: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
) -> pd.DataFrame:
    if normative_df is None:
        return pd.DataFrame()

    target = query_structural_features(structural_df, diagnosis=diagnosis, roi=roi, metric=metric)
    reference = query_structural_features(normative_df, diagnosis=diagnosis, roi=roi, metric=metric)
    if target.empty or reference.empty or "value_numeric" not in target.columns or "value_numeric" not in reference.columns:
        return pd.DataFrame()

    ref_mean = reference["value_numeric"].mean()
    ref_std = reference["value_numeric"].std()
    out = target[["subject_id", "diagnosis_normalized", "roi_name_normalized", "imaging_metric_normalized", "value_numeric"]].copy()
    out["reference_mean"] = ref_mean
    out["reference_std"] = ref_std
    out["z_like_difference"] = None if pd.isna(ref_std) or ref_std == 0 else (out["value_numeric"] - ref_mean) / ref_std
    return out


def load_quantitative_reference_registry(path: str | Path) -> pd.DataFrame:
    """Load manually audited group statistics extracted from paper tables."""
    registry_path = Path(path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Quantitative reference registry not found: {registry_path}")
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Quantitative reference registry must contain a JSON list")
    out = pd.DataFrame(data)
    age_registry_path = registry_path.with_name("age_reference_populations.json")
    if age_registry_path.exists():
        age_data = json.loads(age_registry_path.read_text(encoding="utf-8"))
        if not isinstance(age_data, list):
            raise ValueError("Age reference registry must contain a JSON list")
        age_df = pd.DataFrame(age_data)
        if not age_df.empty:
            if "reference_id" not in age_df.columns or age_df["reference_id"].duplicated().any():
                raise ValueError("Age reference registry requires one unique row per reference_id")
            age_columns = [
                "reference_id",
                "reference_age_min",
                "reference_age_max",
                "reference_age_source",
                "screening_role",
                "interpretation_note",
            ]
            out = out.merge(
                age_df[[column for column in age_columns if column in age_df.columns]],
                on="reference_id",
                how="left",
                validate="many_to_one",
            )
    audit_defaults = {
        "atlas_name": "not reported",
        "atlas_version": "not reported",
        "parcellation_method": "not reported",
        "processing_software": "not reported",
        "processing_software_version": "not reported",
        "atlas_compatibility_status": "not_assessed",
        "license": "not recorded",
        "license_url": None,
        "license_status": "not_assessed",
        "extraction_method": "manual table transcription",
        "manual_review_status": "pending_human_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "verification_note": None,
    }
    for column, default in audit_defaults.items():
        if column not in out.columns:
            out[column] = default
        else:
            out[column] = out[column].where(out[column].notna(), default)
    for column in ["mean", "standard_deviation", "sample_size", "reference_age_min", "reference_age_max"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out["diagnosis_normalized"] = out["diagnosis"].apply(normalize_diagnosis_label)
    out["roi_name_normalized"] = out["roi_name"].apply(normalize_roi_label)
    out["imaging_metric_normalized"] = out["imaging_metric"].apply(normalize_metric_label)
    out["hemisphere_normalized"] = out["hemisphere"].map(normalize_hemisphere_label)
    out["unit_normalized"] = out["unit"].astype(str).str.strip().str.lower()
    return out


def prepare_patient_reference_features(structural_df: pd.DataFrame, subject_id: str) -> pd.DataFrame:
    """Prepare measured and explicitly derived patient features for paper comparison."""
    patient = query_structural_features(structural_df, subject_id=subject_id)
    if patient.empty:
        return patient

    patient = patient.copy()
    patient["feature_derivation"] = "measured FreeSurfer row"
    patient["hemisphere_normalized"] = patient["hemisphere"].map(normalize_hemisphere_label)
    patient["unit_normalized"] = patient["unit"].astype(str).str.strip().str.lower()

    derived_rows = []
    bilateral_volume_rows = patient[
        patient["imaging_metric_normalized"].eq("roi_volume")
        & patient["hemisphere_normalized"].isin(["lh", "rh"])
        & patient["value_numeric"].notna()
    ]
    for roi_name, roi_rows in bilateral_volume_rows.groupby("roi_name_normalized", dropna=False):
        hemispheres = set(roi_rows["hemisphere_normalized"])
        if not roi_name or not {"lh", "rh"}.issubset(hemispheres):
            continue
        first = roi_rows.iloc[0]
        derived_rows.append(
            {
                "subject_id": subject_id,
                "diagnosis": first.get("diagnosis"),
                "diagnosis_normalized": first.get("diagnosis_normalized"),
                "sex": first.get("sex"),
                "age": first.get("age"),
                "mmse": first.get("mmse"),
                "cdr": first.get("cdr"),
                "roi_name": roi_name,
                "roi_name_normalized": roi_name,
                "imaging_metric": "roi_volume",
                "imaging_metric_normalized": "roi_volume",
                "value_numeric": float(roi_rows.groupby("hemisphere_normalized")["value_numeric"].first().sum()),
                "unit": "mm3",
                "unit_normalized": "mm3",
                "hemisphere": "bilateral",
                "hemisphere_normalized": "bilateral",
                "source_pipeline": "FreeSurfer",
                "atlas_name": first.get("atlas_name"),
                "atlas_version": first.get("atlas_version"),
                "parcellation_method": first.get("parcellation_method"),
                "processing_software": first.get("processing_software"),
                "processing_software_version": first.get("processing_software_version"),
                "feature_derivation": "sum of matched left and right FreeSurfer ROI rows",
            }
        )

    bilateral_by_roi = {
        row["roi_name_normalized"]: row
        for row in derived_rows
        if row.get("imaging_metric_normalized") == "roi_volume"
    }
    mtl_components = ["hippocampus", "amygdala", "entorhinal cortex", "parahippocampal gyrus"]
    if all(component in bilateral_by_roi for component in mtl_components):
        first = bilateral_by_roi["hippocampus"]
        component_atlases = sorted(
            {
                str(bilateral_by_roi[component].get("atlas_name"))
                for component in mtl_components
                if bilateral_by_roi[component].get("atlas_name")
            }
        )
        derived_rows.append(
            {
                **first,
                "roi_name": "medial temporal lobe",
                "roi_name_normalized": "medial temporal lobe",
                "value_numeric": float(sum(bilateral_by_roi[component]["value_numeric"] for component in mtl_components)),
                "atlas_name": " + ".join(component_atlases),
                "parcellation_method": "sum of bilateral hippocampus, amygdala, entorhinal and parahippocampal volumes",
                "feature_derivation": "derived bilateral MTL total from four prespecified FreeSurfer regions",
            }
        )
    thickness_rows = patient[
        patient["imaging_metric_normalized"].eq("cortical_thickness")
        & patient["value_numeric"].notna()
    ]
    if not thickness_rows.empty:
        first = thickness_rows.iloc[0]
        thickness_atlases = sorted(
            {str(value) for value in thickness_rows["atlas_name"].dropna().unique()}
        ) if "atlas_name" in thickness_rows.columns else []
        derived_rows.append(
            {
                "subject_id": subject_id,
                "diagnosis": first.get("diagnosis"),
                "diagnosis_normalized": first.get("diagnosis_normalized"),
                "sex": first.get("sex"),
                "age": first.get("age"),
                "mmse": first.get("mmse"),
                "cdr": first.get("cdr"),
                "roi_name": "whole brain cortex",
                "roi_name_normalized": "whole brain cortex",
                "imaging_metric": "cortical_thickness",
                "imaging_metric_normalized": "cortical_thickness",
                "value_numeric": float(thickness_rows["value_numeric"].mean()),
                "unit": "mm",
                "unit_normalized": "mm",
                "hemisphere": "bilateral",
                "hemisphere_normalized": "bilateral",
                "source_pipeline": "FreeSurfer",
                "atlas_name": " + ".join(thickness_atlases) or first.get("atlas_name"),
                "atlas_version": thickness_rows.iloc[0].get("atlas_version", "not encoded in aparc.stats"),
                "processing_software": "FreeSurfer",
                "processing_software_version": thickness_rows.iloc[0].get("processing_software_version", "8.2.0"),
                "parcellation_method": "unweighted mean across aparc cortical parcels",
                "feature_derivation": "unweighted mean of available lh/rh aparc cortical-thickness rows",
            }
        )

    if derived_rows:
        patient = pd.concat([patient, pd.DataFrame(derived_rows)], ignore_index=True, sort=False)
    return patient


def _gaussian_logpdf(value: float, mean: float, standard_deviation: float) -> float:
    z = (value - mean) / standard_deviation
    return -0.5 * (z**2) - math.log(standard_deviation) - 0.5 * math.log(2 * math.pi)


def compare_patient_to_quantitative_references(
    structural_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    subject_id: str,
) -> pd.DataFrame:
    """Compare one patient's harmonized features with disease/control paper distributions.

    The resulting likelihood ratios are research evidence scores, not clinical
    probabilities. Rows without compatible units or complete group statistics
    remain visible but are excluded from ranking.
    """
    patient = prepare_patient_reference_features(structural_df, subject_id)
    if patient.empty:
        return pd.DataFrame()

    refs = reference_df.copy()
    required_normalized = {
        "diagnosis_normalized": ("diagnosis", normalize_diagnosis_label),
        "roi_name_normalized": ("roi_name", normalize_roi_label),
        "imaging_metric_normalized": ("imaging_metric", normalize_metric_label),
        "hemisphere_normalized": ("hemisphere", normalize_hemisphere_label),
    }
    for output_column, (input_column, normalizer) in required_normalized.items():
        if output_column not in refs.columns:
            refs[output_column] = refs[input_column].map(normalizer)
    if "unit_normalized" not in refs.columns:
        refs["unit_normalized"] = refs["unit"].astype(str).str.strip().str.lower()

    disease_refs = refs[~refs["diagnosis_normalized"].isin(["Control", ""])]
    rows = []
    for _, ref in disease_refs.iterrows():
        feature_match = patient[
            patient["roi_name_normalized"].eq(ref["roi_name_normalized"])
            & patient["imaging_metric_normalized"].eq(ref["imaging_metric_normalized"])
            & patient["hemisphere_normalized"].fillna("unspecified").eq(ref.get("hemisphere_normalized") or "unspecified")
        ]
        control_match = refs[
            refs["reference_id"].eq(ref["reference_id"])
            & refs["diagnosis_normalized"].eq("Control")
            & refs["roi_name_normalized"].eq(ref["roi_name_normalized"])
            & refs["imaging_metric_normalized"].eq(ref["imaging_metric_normalized"])
            & refs["hemisphere_normalized"].fillna("unspecified").eq(ref.get("hemisphere_normalized") or "unspecified")
        ]

        base = {
            "subject_id": subject_id,
            "patient_diagnosis": patient.iloc[0].get("diagnosis_normalized"),
            "sex": patient.iloc[0].get("sex"),
            "age": patient.iloc[0].get("age"),
            "mmse": patient.iloc[0].get("mmse"),
            "cdr": patient.iloc[0].get("cdr"),
            "candidate_disease": ref["diagnosis_normalized"],
            "reference_id": ref.get("reference_id"),
            "paper_code": ref.get("paper_code"),
            "source_title": ref.get("source_title"),
            "doi": ref.get("doi"),
            "source_url": ref.get("source_url"),
            "table_or_figure": ref.get("table_or_figure"),
            "roi_name": ref["roi_name_normalized"],
            "hemisphere": ref.get("hemisphere_normalized"),
            "imaging_metric": ref["imaging_metric_normalized"],
            "reference_unit": ref.get("unit_normalized"),
            "disease_mean": ref.get("mean"),
            "disease_sd": ref.get("standard_deviation"),
            "pathology_confirmation": ref.get("pathology_confirmation"),
            "evidence_note": ref.get("evidence_note"),
            "reference_atlas_name": ref.get("atlas_name"),
            "reference_atlas_version": ref.get("atlas_version"),
            "reference_parcellation_method": ref.get("parcellation_method"),
            "reference_processing_software": ref.get("processing_software"),
            "reference_processing_software_version": ref.get("processing_software_version"),
            "atlas_compatibility_status": ref.get("atlas_compatibility_status"),
            "license": ref.get("license"),
            "license_url": ref.get("license_url"),
            "license_status": ref.get("license_status"),
            "reference_manual_review_status": ref.get("manual_review_status"),
            "reference_age_min": ref.get("reference_age_min"),
            "reference_age_max": ref.get("reference_age_max"),
            "reference_age_source": ref.get("reference_age_source"),
            "reviewed_by": ref.get("reviewed_by"),
            "reviewed_at": ref.get("reviewed_at"),
            "manual_review_status": "comparison_requires_case_level_review",
        }

        if feature_match.empty:
            rows.append({**base, "comparison_status": "patient_feature_unavailable", "included_in_ranking": False})
            continue

        patient_row = feature_match.iloc[0]
        patient_value = pd.to_numeric(pd.Series([patient_row.get("value_numeric")]), errors="coerce").iloc[0]
        patient_age = pd.to_numeric(pd.Series([patient_row.get("age")]), errors="coerce").iloc[0]
        reference_age_min = pd.to_numeric(pd.Series([ref.get("reference_age_min")]), errors="coerce").iloc[0]
        reference_age_max = pd.to_numeric(pd.Series([ref.get("reference_age_max")]), errors="coerce").iloc[0]
        patient_unit = patient_row.get("unit_normalized")
        row = {
            **base,
            "patient_value": patient_value,
            "patient_unit": patient_unit,
            "feature_derivation": patient_row.get("feature_derivation"),
            "patient_atlas_name": patient_row.get("atlas_name"),
            "patient_atlas_version": patient_row.get("atlas_version"),
            "patient_parcellation_method": patient_row.get("parcellation_method"),
            "patient_processing_software": patient_row.get("processing_software"),
            "patient_processing_software_version": patient_row.get("processing_software_version"),
        }

        # Age is an applicability gate for the paper cohort, not a disease label.
        # A patient outside the source population must not be scored by that model.
        if pd.isna(patient_age):
            rows.append({**row, "age_applicability_status": "patient_age_unavailable", "comparison_status": "patient_age_unavailable", "included_in_ranking": False})
            continue
        if pd.notna(reference_age_min) and patient_age < reference_age_min:
            rows.append({**row, "age_applicability_status": "below_reference_age_range", "comparison_status": "age_outside_reference_population", "included_in_ranking": False})
            continue
        if pd.notna(reference_age_max) and patient_age > reference_age_max:
            rows.append({**row, "age_applicability_status": "above_reference_age_range", "comparison_status": "age_outside_reference_population", "included_in_ranking": False})
            continue
        age_status = (
            "within_reference_age_range"
            if pd.notna(reference_age_min) or pd.notna(reference_age_max)
            else "reference_age_range_unavailable"
        )
        row["age_applicability_status"] = age_status

        if patient_unit != ref.get("unit_normalized"):
            rows.append({**row, "comparison_status": "unit_mismatch", "included_in_ranking": False})
            continue
        if not bool(ref.get("comparison_compatible", False)):
            rows.append({**row, "comparison_status": "reference_not_harmonized", "included_in_ranking": False})
            continue
        compatible_atlas_states = {
            "exact_match",
            "compatible_family",
            "compatible_family_version_unreported",
            "global_not_atlas_dependent",
        }
        if ref.get("atlas_compatibility_status") not in compatible_atlas_states:
            rows.append({**row, "comparison_status": "atlas_or_parcellation_not_harmonized", "included_in_ranking": False})
            continue
        if ref.get("manual_review_status") != "manually_verified_against_source":
            rows.append({**row, "comparison_status": "reference_pending_manual_verification", "included_in_ranking": False})
            continue
        if control_match.empty:
            rows.append({**row, "comparison_status": "control_distribution_unavailable", "included_in_ranking": False})
            continue

        control = control_match.iloc[0]
        disease_mean = pd.to_numeric(pd.Series([ref.get("mean")]), errors="coerce").iloc[0]
        disease_sd = pd.to_numeric(pd.Series([ref.get("standard_deviation")]), errors="coerce").iloc[0]
        control_mean = pd.to_numeric(pd.Series([control.get("mean")]), errors="coerce").iloc[0]
        control_sd = pd.to_numeric(pd.Series([control.get("standard_deviation")]), errors="coerce").iloc[0]
        row.update({"control_mean": control_mean, "control_sd": control_sd})
        if any(pd.isna(value) for value in [patient_value, disease_mean, disease_sd, control_mean, control_sd]) or disease_sd <= 0 or control_sd <= 0:
            rows.append({**row, "comparison_status": "complete_mean_sd_unavailable", "included_in_ranking": False})
            continue

        disease_z = (patient_value - disease_mean) / disease_sd
        control_z = (patient_value - control_mean) / control_sd
        log_likelihood_ratio = _gaussian_logpdf(patient_value, disease_mean, disease_sd) - _gaussian_logpdf(patient_value, control_mean, control_sd)
        rows.append(
            {
                **row,
                "disease_z": disease_z,
                "control_z": control_z,
                "log_likelihood_ratio_vs_control": log_likelihood_ratio,
                "feature_supports_disease_over_control": log_likelihood_ratio > 0,
                "comparison_status": "ranked_gaussian_likelihood_ratio",
                "included_in_ranking": True,
            }
        )
    return pd.DataFrame(rows)


def rank_candidate_diseases(quantitative_comparison_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate feature likelihood ratios without inventing a one-candidate rank.

    A softmax over a single disease is always 1.0, even when every feature is
    closer to the matched Control distribution.  Compatibility shares are
    therefore reported only when at least two disease candidates are available.
    """
    if quantitative_comparison_df.empty:
        return pd.DataFrame()
    ranked = quantitative_comparison_df[quantitative_comparison_df["included_in_ranking"].eq(True)].copy()
    if ranked.empty:
        return pd.DataFrame()
    ranked["feature_supports_disease_over_control"] = (
        ranked["feature_supports_disease_over_control"].astype("boolean").fillna(False).astype(int)
    )
    summary = (
        ranked.groupby("candidate_disease", dropna=False)
        .agg(
            n_comparable_features=("included_in_ranking", "sum"),
            n_features_supporting_disease=("feature_supports_disease_over_control", "sum"),
            total_log_likelihood_ratio_vs_control=("log_likelihood_ratio_vs_control", "sum"),
            paper_codes=("paper_code", lambda values: ", ".join(sorted(set(map(str, values))))),
            dois=("doi", lambda values: ", ".join(sorted({str(v) for v in values if pd.notna(v)}))),
        )
        .reset_index()
    )
    summary["evidence_direction"] = summary["total_log_likelihood_ratio_vs_control"].map(
        lambda score: "disease_over_control"
        if score > 0
        else ("control_over_disease" if score < 0 else "inconclusive")
    )
    differential_ranking_available = len(summary) >= 2
    summary["differential_ranking_available"] = differential_ranking_available
    if differential_ranking_available:
        max_score = summary["total_log_likelihood_ratio_vs_control"].max()
        weights = (summary["total_log_likelihood_ratio_vs_control"] - max_score).map(math.exp)
        summary["evidence_compatibility_share"] = weights / weights.sum()
        summary["interpretation"] = summary.apply(
            lambda row: "highest relative imaging-evidence compatibility in current references"
            if row["total_log_likelihood_ratio_vs_control"] == max_score
            else "secondary relative imaging-evidence compatibility",
            axis=1,
        )
    else:
        summary["evidence_compatibility_share"] = pd.NA
        summary["interpretation"] = summary["evidence_direction"].map(
            {
                "disease_over_control": "single disease comparison favors disease; no differential ranking available",
                "control_over_disease": "single disease comparison favors matched Control distribution",
                "inconclusive": "single disease comparison is inconclusive",
            }
        )
    summary["scope_note"] = "Research ranking from selected MRI paper distributions; not a diagnosis or calibrated disease probability."
    return summary.sort_values("total_log_likelihood_ratio_vs_control", ascending=False).reset_index(drop=True)


def evaluate_against_held_out_label(
    structural_df: pd.DataFrame,
    quantitative_comparison_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    subject_id: str,
) -> pd.DataFrame:
    """Compare a label-blind workflow outcome with the held-out recorded label.

    Abstentions are not counted as correct predictions. This keeps technical
    execution success separate from retrospective classification performance.
    """
    patient = query_structural_features(structural_df, subject_id=subject_id)
    if patient.empty:
        return pd.DataFrame(
            [{
                "subject_id": subject_id,
                "workflow_outcome": "ABSTAIN_SUBJECT_NOT_FOUND",
                "held_out_recorded_label": None,
                "retrospective_agreement": pd.NA,
                "evaluation_status": "not_evaluable",
            }]
        )

    held_out_label = patient.iloc[0].get("diagnosis_normalized")
    statuses = set(
        quantitative_comparison_df.get("comparison_status", pd.Series(dtype=str)).dropna()
    )
    if ranking_df.empty:
        if "age_outside_reference_population" in statuses:
            screened_candidates = sorted(
                set(
                    quantitative_comparison_df.loc[
                        quantitative_comparison_df["comparison_status"].eq("age_outside_reference_population"),
                        "candidate_disease",
                    ].dropna().astype(str)
                )
            )
            outcome = "NO_SUPPORTED_DISEASE_CANDIDATE"
            candidate_screening_result = ", ".join(screened_candidates) or "none"
        elif "patient_age_unavailable" in statuses:
            outcome = "ABSTAIN_AGE_UNAVAILABLE"
            candidate_screening_result = "not assessed"
        else:
            outcome = "ABSTAIN_NO_ELIGIBLE_QUANTITATIVE_EVIDENCE"
            candidate_screening_result = "none"
        agreement = pd.NA
        evaluation_status = "not_evaluable"
    else:
        top = ranking_df.iloc[0]
        top_score = float(top["total_log_likelihood_ratio_vs_control"])
        if top_score <= 0:
            outcome = "Control"
        else:
            outcome = str(top["candidate_disease"])
        agreement = normalize_diagnosis_label(outcome) == normalize_diagnosis_label(held_out_label)
        evaluation_status = "match" if agreement else "mismatch"
        candidate_screening_result = "none"

    return pd.DataFrame(
        [{
            "subject_id": subject_id,
            "workflow_outcome": outcome,
            "age_screened_out_candidate_models": candidate_screening_result,
            "held_out_recorded_label": held_out_label,
            "retrospective_agreement": agreement,
            "evaluation_status": evaluation_status,
        }]
    )


def build_quantitative_case_report(
    structural_df: pd.DataFrame,
    quantitative_comparison_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    subject_id: str,
    normative_df: pd.DataFrame | None = None,
    mmc_validation_df: pd.DataFrame | None = None,
) -> str:
    """Build a staged normative and reference-linked research report."""
    patient = query_structural_features(structural_df, subject_id=subject_id)
    lines = ["## Normative and reference-linked MRI evidence report", ""]
    if patient.empty:
        return "\n".join(lines + [f"No structural rows were found for `{subject_id}`."])
    first = patient.iloc[0]
    display_value = lambda value: "not available" if pd.isna(value) or str(value).strip().lower() in {"", "nan", "none", "unknown"} else str(value)
    patient_atlases = sorted(
        {str(value) for value in patient.get("atlas_name", pd.Series(dtype=object)).dropna().unique()}
    )
    software_versions = sorted(
        {
            f"{software} {version}".strip()
            for software, version in zip(
                patient.get("processing_software", pd.Series(dtype=object)),
                patient.get("processing_software_version", pd.Series(dtype=object)),
            )
            if pd.notna(software)
        }
    )
    lines.extend(
        [
            "### 1. Demographics and processing provenance",
            "",
            f"- **Subject:** `{subject_id}`",
            f"- **Sex:** {display_value(first.get('sex'))}",
            f"- **Age:** {display_value(first.get('age'))}",
            f"- **MMSE:** {display_value(first.get('mmse'))}",
            f"- **CDR:** {display_value(first.get('cdr'))}",
            f"- **Processing software:** {', '.join(software_versions) or 'not recorded'}",
            f"- **Atlas / segmentation:** {', '.join(patient_atlases) or 'not recorded'}",
            "",
            "Cortical DKT measurements must originate from `lh/rh.aparc.DKTatlas.stats`. "
            "Hippocampus, amygdala and other subcortical volumes originate from `aseg.stats` and are not DKT cortical parcels.",
            "",
            "### 2. Age-adjusted normative screening",
            "",
        ]
    )
    patient_age = pd.to_numeric(pd.Series([first.get("age")]), errors="coerce").iloc[0]
    if normative_df is None or normative_df.empty:
        within_potvin_range = pd.notna(patient_age) and 18 <= float(patient_age) <= 94
        lines.extend(
            [
                "- **Normative model:** Potvin adult FreeSurfer norms (target integration).",
                f"- **Age coverage check:** {'within' if within_potvin_range else 'outside or unavailable for'} the published 18-94 year range.",
                "- **Cortical reference:** Potvin et al. DKT normative models, DOI [10.1016/j.neuroimage.2017.04.035](https://doi.org/10.1016/j.neuroimage.2017.04.035).",
                "- **Subcortical reference:** Potvin et al. FreeSurfer subcortical norms, DOI [10.1016/j.neuroimage.2016.05.016](https://doi.org/10.1016/j.neuroimage.2016.05.016).",
                "- **Normative calculation status:** not calculated. The Potvin model coefficients/calculator and required covariates "
                "(sex, eTIV, scanner manufacturer and field strength) are not yet loaded into this run.",
                "- **Interpretation:** no ROI should be called abnormally low/high from age alone until an expected value, residual SD, Z score and percentile are available.",
            ]
        )
    else:
        lines.extend(
            [
                f"- **Normative table loaded:** {len(normative_df)} rows.",
                "- **Status:** an empirical reference table is available, but it must be confirmed as age-, sex-, eTIV-, scanner- and atlas-compatible before its Z scores are interpreted as Potvin norms.",
            ]
        )
    if mmc_validation_df is not None and not mmc_validation_df.empty:
        subject_mmc = mmc_validation_df[
            mmc_validation_df.get("subject_id", pd.Series(dtype=str)).astype(str).eq(str(subject_id))
        ]
        if subject_mmc.empty:
            subject_mmc = mmc_validation_df
        ready_counts = (
            subject_mmc.get("mmc_ready_status", pd.Series(dtype=str))
            .fillna("unknown")
            .value_counts()
            .to_dict()
        )
        matched_rows = int(
            subject_mmc.get("patient_feature_status", pd.Series(dtype=str))
            .eq("matching_feature_found")
            .sum()
        )
        atlas_states = ", ".join(
            sorted({str(value) for value in subject_mmc.get("atlas_compatibility_status", pd.Series(dtype=object)).dropna()})
        )
        missing_covariates = sorted(
            {
                str(value)
                for value in subject_mmc.get("missing_covariates", pd.Series(dtype=object)).dropna()
                if str(value).strip()
            }
        )
        lines.extend(
            [
                "",
                "#### MMC / Potvin cross-validation bridge",
                "",
                f"- **MMC ROI slots matched to this workflow:** {matched_rows}",
                f"- **MMC readiness summary:** {ready_counts}",
                f"- **Atlas compatibility:** {atlas_states or 'not assessed'}",
                f"- **Missing MMC covariates:** {', '.join(missing_covariates) if missing_covariates else 'none recorded by the bridge'}",
                "- **Use:** enter the matched observed values and required covariates into the MMC workbook, then import the MMC predicted values, 95% intervals, ZOP and percentiles for external normative validation.",
            ]
        )
    lines.extend(
        [
            "",
            "### 3. Quantitative disease-candidate comparison",
            "",
            "Patient measurements are compared with eligible disease and matched-Control distributions from the paper evidence library. "
            "Age only controls whether a paper model is applicable; it is not used as a disease label.",
            "",
        ]
    )
    retrospective_evaluation = evaluate_against_held_out_label(
        structural_df,
        quantitative_comparison_df,
        ranking_df,
        subject_id,
    ).iloc[0]
    agreement = retrospective_evaluation["retrospective_agreement"]
    agreement_text = "not evaluable" if pd.isna(agreement) else ("match" if agreement else "mismatch")
    lines.extend(
        [
            f"- **Workflow outcome:** {retrospective_evaluation['workflow_outcome']}",
            "",
        ]
    )
    ranked_features = quantitative_comparison_df[
        quantitative_comparison_df.get(
            "included_in_ranking",
            pd.Series(False, index=quantitative_comparison_df.index),
        ).eq(True)
    ] if not quantitative_comparison_df.empty else pd.DataFrame()
    if not ranked_features.empty:
        lines.extend(["#### Paper-relative feature observations", ""])
        lines.append(
            "These Z scores are relative to the disease and matched-Control samples in each cited paper; they are not Potvin normative Z scores."
        )
        for row in ranked_features.head(12).itertuples():
            direction = "closer to disease" if row.log_likelihood_ratio_vs_control > 0 else "closer to matched Control"
            lines.append(
                f"- **{row.roi_name} ({row.hemisphere})**: observed={row.patient_value:g} {row.patient_unit}; "
                f"disease Z={row.disease_z:.2f}; Control Z={row.control_z:.2f}; {direction}; "
                f"reference={row.paper_code}, {row.table_or_figure}."
            )
        lines.append("")
    if ranking_df.empty:
        statuses = set(quantitative_comparison_df.get("comparison_status", pd.Series(dtype=str)).dropna())
        if "age_outside_reference_population" in statuses:
            age_ranges = (
                quantitative_comparison_df.loc[
                    quantitative_comparison_df["comparison_status"].eq("age_outside_reference_population"),
                    ["source_title", "reference_age_min", "reference_age_max"],
                ]
                .drop_duplicates()
            )
            ranges = "; ".join(
                f"{row.source_title}: {row.reference_age_min:g}-{row.reference_age_max:g} years"
                for row in age_ranges.itertuples()
            )
            lines.append(
                "The age screen removed the affected candidate reference model(s) from numerical ranking because the patient's age is outside the source population. "
                f"Reference range(s): {ranges}. The workflow continued to evaluate the remaining disease candidates, but none currently has another eligible quantitative model. "
                "Therefore the result is **no disease type supported by the current evidence library**. This does not stop the workflow and does not clinically rule out the screened disease."
            )
        elif "patient_age_unavailable" in statuses:
            lines.append("No disease ranking was calculated because patient age is unavailable for the required reference-population applicability check.")
        else:
            lines.append("No disease ranking can be calculated because no patient feature has a harmonized disease/control paper distribution with complete mean and SD.")
    else:
        top = ranking_df.iloc[0]
        top_score = float(top["total_log_likelihood_ratio_vs_control"])
        has_differential_ranking = bool(top.get("differential_ranking_available", len(ranking_df) >= 2))
        if not has_differential_ranking:
            candidate = top["candidate_disease"]
            if top_score < 0:
                lines.append(
                    f"Only one eligible disease comparison is currently available ({candidate} vs matched Control). "
                    f"The aggregate evidence direction **favours the matched Control distribution over {candidate}** "
                    f"(log likelihood ratio={top_score:.3f}; {int(top['n_comparable_features'])} comparable features)."
                )
            elif top_score > 0:
                lines.append(
                    f"Only one eligible disease comparison is currently available ({candidate} vs matched Control). "
                    f"The aggregate imaging signal favours {candidate} over that matched Control distribution "
                    f"(log likelihood ratio={top_score:.3f}; {int(top['n_comparable_features'])} comparable features), "
                    "but **no differential disease ranking can be calculated**."
                )
            else:
                lines.append(
                    f"The only eligible comparison ({candidate} vs matched Control) is inconclusive; "
                    "no differential disease ranking can be calculated."
                )
            lines.append("A compatibility share is intentionally not reported for a single disease candidate because it would always equal 1.000.")
        elif top_score <= 0:
            lines.append(
                "All currently eligible disease comparisons favour their matched Control distributions. "
                "The workflow therefore does **not identify a supported disease candidate** from the available quantitative references."
            )
        else:
            lines.append(
                f"Among the currently included and numerically compatible disease references, this patient's MRI features have the "
                f"**highest relative evidence compatibility with {top['candidate_disease']}** "
                f"(compatibility share={top['evidence_compatibility_share']:.3f}; {int(top['n_comparable_features'])} comparable features)."
            )
            lines.append("This compatibility share is a relative research score, not a clinical probability.")
        lines.append("")
        for rank, (_, candidate) in enumerate(ranking_df.iterrows(), start=1):
            candidate_rows = quantitative_comparison_df[
                quantitative_comparison_df["candidate_disease"].eq(candidate["candidate_disease"])
                & quantitative_comparison_df["included_in_ranking"].eq(True)
            ]
            references = []
            for row in candidate_rows.drop_duplicates(["paper_code", "table_or_figure"]).itertuples():
                doi_text = (
                    f"[DOI {row.doi}](https://doi.org/{row.doi})"
                    if pd.notna(row.doi) and str(row.doi).strip()
                    else "DOI not reported"
                )
                source_text = (
                    f"[source]({row.source_url})"
                    if pd.notna(row.source_url) and str(row.source_url).strip()
                    else "source URL not reported"
                )
                references.append(
                    f"**{row.paper_code}**: {row.source_title} ({doi_text}; {source_text}; "
                    f"{row.table_or_figure}; atlas={row.reference_atlas_name}; "
                    f"software={row.reference_processing_software} {row.reference_processing_software_version}; "
                    f"license={row.license})"
                )
            reference_text = "; ".join(references)
            share = candidate.get("evidence_compatibility_share")
            share_text = f"{float(share):.3f}" if pd.notna(share) else "not calculated (single disease candidate)"
            lines.append(
                f"{rank}. **{candidate['candidate_disease']} comparison:** evidence direction={candidate['evidence_direction']}; "
                f"aggregate log likelihood ratio vs Control={candidate['total_log_likelihood_ratio_vs_control']:.3f}; "
                f"relative compatibility share={share_text}; supporting features="
                f"{int(candidate['n_features_supporting_disease'])}/{int(candidate['n_comparable_features'])}. References: {reference_text}"
            )

    unavailable = quantitative_comparison_df[
        ~quantitative_comparison_df.get("included_in_ranking", pd.Series(False, index=quantitative_comparison_df.index)).eq(True)
    ] if not quantitative_comparison_df.empty else pd.DataFrame()
    if not unavailable.empty:
        lines.extend(["", "### 4. Evidence audit: not used in numeric ranking"])
        for row in unavailable.drop_duplicates(["candidate_disease", "paper_code", "comparison_status"]).itertuples():
            lines.append(
                f"- {row.candidate_disease}: {row.paper_code}, status=`{row.comparison_status}`. "
                f"{row.evidence_note} Source: {row.source_url}; DOI: {row.doi}."
            )
    lines.extend(
        [
            "",
            "### 5. Retrospective validation (revealed after scoring)",
            "",
            f"- **Held-out recorded label:** {retrospective_evaluation['held_out_recorded_label']}",
            f"- **Agreement with label-blind workflow outcome:** {agreement_text}",
            "- The recorded label was not used to select references, calculate feature likelihoods, or rank candidates.",
        ]
    )
    controls = structural_df[
        structural_df.get("diagnosis_normalized", pd.Series(index=structural_df.index, dtype=object)).eq("Control")
    ].copy()
    patient_age = pd.to_numeric(pd.Series([first.get("age")]), errors="coerce").iloc[0]
    control_ages = pd.to_numeric(controls.get("age", pd.Series(dtype=float)), errors="coerce").dropna()
    lines.extend(["", "### 6. Recommendations and limitations"])
    lines.append("- Treat every comparison as research decision support until a reviewer records an explicit case-level acceptance or rejection with a dated note.")
    if len(ranking_df) < 2:
        lines.append("- Add atlas-, hemisphere-, unit-, and method-compatible disease/Control distributions for FTD and other differential diagnoses before interpreting the ranking as disease discrimination.")
    if pd.notna(patient_age) and not control_ages.empty and abs(float(control_ages.median()) - float(patient_age)) > 10:
        lines.append(
            f"- Replace or supplement the pilot Controls with age-matched normative data; patient age is {patient_age:g}, "
            f"whereas the current Control median age is {float(control_ages.median()):g}."
        )
    lines.extend(
        [
            "- Verify the named atlas/parcellation, processing software version, ROI definition, sample size, mean, SD, and license against each source paper before enabling a new reference row for ranking.",
            "- Where clinically appropriate, combine structural MRI evidence with neurological assessment, cognitive testing, and independent amyloid/tau or other biomarker evidence.",
            "- Do not use this report for treatment selection or communicate the compatibility share as a diagnostic probability.",
        ]
    )
    lines.extend(
        [
            "",
            "### Interpretation boundary",
            "Structural MRI reflects regional anatomy, not direct amyloid/tau or histopathological confirmation. A disease-level conclusion requires clinical assessment and, where appropriate, patient biomarker evidence such as amyloid/tau PET, CSF, or blood biomarkers.",
        ]
    )
    return "\n".join(lines)


def score_structural_match_for_diagnosis(row: pd.Series, diagnosis: str) -> int:
    diagnosis_norm = normalize_diagnosis_label(diagnosis)
    signature = DIAGNOSIS_SIGNATURES.get(diagnosis_norm, {})
    score = 0
    roi = normalize_roi_label(row.get("roi_name_normalized") or row.get("roi_name"))
    metric = normalize_metric_label(row.get("imaging_metric_normalized") or row.get("imaging_metric"))
    if roi and roi in signature.get("rois", set()):
        score += 2
    if metric and metric in signature.get("metrics", set()):
        score += 1
    return score


def summarize_diagnosis_support(
    structural_df: pd.DataFrame,
    records: list[dict[str, Any]] | list[LiteratureRecord],
    subject_id: str | None = None,
) -> pd.DataFrame:
    """Conservative single-case support summary for the prototype.

    Do not rank diagnoses from structural signatures alone. A non-zero score
    requires actual literature rows matched to measured ROI/metric rows.
    """
    structural = normalize_structural_dataframe(structural_df)
    if subject_id is not None and "subject_id" in structural.columns:
        structural = structural[structural["subject_id"].astype(str) == str(subject_id)]
    evidence_df = build_evidence_framework(records)
    rows = []
    diagnoses = sorted({d for d in evidence_df.get("diagnosis_normalized", pd.Series(dtype=str)).dropna().astype(str).tolist()})
    for diagnosis in diagnoses:
        matches = compare_features_to_literature(structural, evidence_df, diagnosis=diagnosis)
        literature_match_rows = int(matches["evidence_match"].sum()) if not matches.empty and "evidence_match" in matches.columns else 0
        rows.append({
            "diagnosis": diagnosis,
            "measured_structural_rows": int(len(structural)),
            "structural_signature_score": 0,
            "signature_hits": "not_used_in_single_case_prototype",
            "literature_match_rows": literature_match_rows,
            "combined_support_score": literature_match_rows,
            "ranking_interpretation": "candidate support only; not diagnostic" if literature_match_rows > 0 else "no matched evidence in current single-case feature set",
            "scope_note": "single-case prototype; no group comparison or diagnostic inference",
        })
    return pd.DataFrame(rows).sort_values(["combined_support_score", "literature_match_rows"], ascending=False).reset_index(drop=True)

def build_interpretive_report(
    structural_df: pd.DataFrame,
    records: list[dict[str, Any]] | list[LiteratureRecord],
    subject_id: str | None = None,
    diagnosis: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
) -> str:
    structural_rows = query_structural_features(structural_df, subject_id=subject_id, diagnosis=diagnosis, roi=roi, metric=metric)
    evidence_df = build_evidence_framework(records)
    evidence_rows = compare_features_to_literature(structural_rows, evidence_df, diagnosis=diagnosis, roi=roi, metric=metric)
    diagnosis_support = summarize_diagnosis_support(structural_rows, records, subject_id=subject_id)

    lines = [
        "# Structured Interpretive Report",
        "",
        "## Scope",
        f"- subject_id: {subject_id}",
        f"- diagnosis filter: {diagnosis}",
        f"- roi filter: {roi}",
        f"- imaging_metric filter: {metric}",
        "",
        "## Structural MRI Summary",
        f"- matched structural rows: {len(structural_rows)}",
    ]
    if "source_pipeline" in structural_rows.columns and not structural_rows.empty:
        pipelines = sorted({str(x) for x in structural_rows["source_pipeline"].dropna().tolist()})
        if pipelines:
            lines.append(f"- source pipelines: {', '.join(pipelines)}")

    lines.extend(
        [
            "",
            "## Candidate Literature-Linked Evidence (manual review required)",
            f"- evidence-linked rows: {len(evidence_rows)}",
        ]
    )
    if not evidence_rows.empty:
        top_titles = dedupe_strings([str(x) for x in evidence_rows["source_title"].dropna().tolist()])[:5]
        if top_titles:
            lines.append("- example supporting sources:")
            for title in top_titles:
                lines.append(f"  - {title}")
    else:
        lines.append("- no direct literature match was found for the current filter")

    lines.extend(["", "## Diagnosis Support Ranking"])
    if not diagnosis_support.empty:
        for _, row in diagnosis_support.head(5).iterrows():
            lines.append(
                f"- {row['diagnosis']}: combined={row['combined_support_score']} "
                f"(structural={row['structural_signature_score']}, literature={row['literature_match_rows']})"
            )
    else:
        lines.append("- no diagnosis support summary could be generated")

    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "- This workflow provides evidence-informed interpretive support, not automated diagnosis.",
            "- Disease support is derived from both structural-feature signatures and literature-linked matches.",
            "- Pipeline choice, preprocessing variability, cohort context, and incomplete literature coverage should remain visible in interpretation.",
        ]
    )
    return "\n".join(lines)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def build_sql(records: list[LiteratureRecord]) -> str:
    statements = [
        "CREATE TABLE IF NOT EXISTS source_documents (source_id SERIAL PRIMARY KEY, source_label TEXT, source_type TEXT, source_path_or_url TEXT, extraction_mode TEXT);",
        "CREATE TABLE IF NOT EXISTS papers (paper_id SERIAL PRIMARY KEY, source_id INT REFERENCES source_documents(source_id), title TEXT, publication_year INT, doi TEXT, study_design TEXT, population TEXT, abstract_like_summary TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_authors (paper_id INT REFERENCES papers(paper_id), author_order INT, author_name TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_diagnoses (paper_id INT REFERENCES papers(paper_id), diagnosis TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_modalities (paper_id INT REFERENCES papers(paper_id), modality TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_rois (paper_id INT REFERENCES papers(paper_id), roi_name TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_symptoms (paper_id INT REFERENCES papers(paper_id), diagnosis TEXT, symptom TEXT, evidence_note TEXT);",
        "CREATE TABLE IF NOT EXISTS roi_observations (observation_id SERIAL PRIMARY KEY, paper_id INT REFERENCES papers(paper_id), diagnosis TEXT, sex_scope TEXT, data_level TEXT, roi_name TEXT, imaging_metric TEXT, statistic_type TEXT, value_numeric DOUBLE PRECISION, unit TEXT, n_total INT, evidence_note TEXT);",
        "CREATE TABLE IF NOT EXISTS paper_findings (paper_id INT REFERENCES papers(paper_id), finding_type TEXT, finding_text TEXT);",
        "",
        "BEGIN;",
    ]

    for idx, record in enumerate(records, start=1):
        source_id = idx
        paper_id = idx
        statements.append(
            "INSERT INTO source_documents (source_id, source_label, source_type, source_path_or_url, extraction_mode) VALUES "
            f"({source_id}, {sql_literal(record.source_label)}, {sql_literal(record.source_type)}, {sql_literal(record.source_path_or_url)}, {sql_literal(record.extraction_mode)});"
        )
        statements.append(
            "INSERT INTO papers (paper_id, source_id, title, publication_year, doi, study_design, population, abstract_like_summary) VALUES "
            f"({paper_id}, {source_id}, {sql_literal(record.title)}, {sql_literal(record.year)}, {sql_literal(record.doi)}, {sql_literal(record.study_design)}, {sql_literal(record.population)}, {sql_literal(record.abstract_like_summary)});"
        )
        for order, author in enumerate(record.authors, start=1):
            statements.append(
                f"INSERT INTO paper_authors (paper_id, author_order, author_name) VALUES ({paper_id}, {order}, {sql_literal(author)});"
            )
        for diagnosis in record.diagnoses:
            statements.append(
                f"INSERT INTO paper_diagnoses (paper_id, diagnosis) VALUES ({paper_id}, {sql_literal(diagnosis)});"
            )
        for modality in record.modalities:
            statements.append(
                f"INSERT INTO paper_modalities (paper_id, modality) VALUES ({paper_id}, {sql_literal(modality)});"
            )
        for roi in record.rois:
            statements.append(
                f"INSERT INTO paper_rois (paper_id, roi_name) VALUES ({paper_id}, {sql_literal(roi)});"
            )
        diagnosis_scope = record.diagnoses or [None]
        for symptom in record.symptoms:
            for diagnosis in diagnosis_scope:
                statements.append(
                    "INSERT INTO paper_symptoms (paper_id, diagnosis, symptom, evidence_note) VALUES "
                    f"({paper_id}, {sql_literal(diagnosis)}, {sql_literal(symptom)}, {sql_literal(record.title)});"
                )
        roi_scope = record.rois or [None]
        metric_scope = record.imaging_metrics or [None]
        sex_scope = record.sex_scope or [None]
        for diagnosis in diagnosis_scope:
            for roi in roi_scope:
                for metric in metric_scope:
                    if roi is None and metric is None:
                        continue
                    for sex in sex_scope:
                        statements.append(
                            "INSERT INTO roi_observations (paper_id, diagnosis, sex_scope, data_level, roi_name, imaging_metric, statistic_type, value_numeric, unit, n_total, evidence_note) VALUES "
                            f"({paper_id}, {sql_literal(diagnosis)}, {sql_literal(sex)}, 'group_summary', {sql_literal(roi)}, {sql_literal(metric)}, 'qualitative_pattern', NULL, NULL, NULL, {sql_literal(record.title)});"
                        )
        for finding in record.findings:
            statements.append(
                f"INSERT INTO paper_findings (paper_id, finding_type, finding_text) VALUES ({paper_id}, 'finding', {sql_literal(finding)});"
            )
        for limitation in record.limitations:
            statements.append(
                f"INSERT INTO paper_findings (paper_id, finding_type, finding_text) VALUES ({paper_id}, 'limitation', {sql_literal(limitation)});"
            )

    statements.append("COMMIT;")
    return "\n".join(statements)


def initialize_sqlite_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS source_documents (
            source_id INTEGER PRIMARY KEY,
            source_label TEXT,
            source_type TEXT,
            source_path_or_url TEXT,
            extraction_mode TEXT
        );

        CREATE TABLE IF NOT EXISTS papers (
            paper_id INTEGER PRIMARY KEY,
            source_id INTEGER REFERENCES source_documents(source_id),
            title TEXT,
            publication_year INTEGER,
            doi TEXT,
            study_design TEXT,
            population TEXT,
            abstract_like_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_authors (
            paper_id INTEGER REFERENCES papers(paper_id),
            author_order INTEGER,
            author_name TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_diagnoses (
            paper_id INTEGER REFERENCES papers(paper_id),
            diagnosis TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_modalities (
            paper_id INTEGER REFERENCES papers(paper_id),
            modality TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_rois (
            paper_id INTEGER REFERENCES papers(paper_id),
            roi_name TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_symptoms (
            paper_id INTEGER REFERENCES papers(paper_id),
            diagnosis TEXT,
            symptom TEXT,
            evidence_note TEXT
        );

        CREATE TABLE IF NOT EXISTS roi_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER REFERENCES papers(paper_id),
            diagnosis TEXT,
            sex_scope TEXT,
            data_level TEXT,
            roi_name TEXT,
            imaging_metric TEXT,
            statistic_type TEXT,
            value_numeric REAL,
            unit TEXT,
            n_total INTEGER,
            evidence_note TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_findings (
            paper_id INTEGER REFERENCES papers(paper_id),
            finding_type TEXT,
            finding_text TEXT
        );
        """
    )


def write_sqlite(records: list[LiteratureRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_path) as connection:
        initialize_sqlite_database(connection)

        connection.execute("DELETE FROM paper_authors")
        connection.execute("DELETE FROM paper_diagnoses")
        connection.execute("DELETE FROM paper_modalities")
        connection.execute("DELETE FROM paper_rois")
        connection.execute("DELETE FROM paper_symptoms")
        connection.execute("DELETE FROM roi_observations")
        connection.execute("DELETE FROM paper_findings")
        connection.execute("DELETE FROM papers")
        connection.execute("DELETE FROM source_documents")

        for idx, record in enumerate(records, start=1):
            source_id = idx
            paper_id = idx
            connection.execute(
                """
                INSERT INTO source_documents (
                    source_id,
                    source_label,
                    source_type,
                    source_path_or_url,
                    extraction_mode
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    record.source_label,
                    record.source_type,
                    record.source_path_or_url,
                    record.extraction_mode,
                ),
            )
            connection.execute(
                """
                INSERT INTO papers (
                    paper_id,
                    source_id,
                    title,
                    publication_year,
                    doi,
                    study_design,
                    population,
                    abstract_like_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    source_id,
                    record.title,
                    record.year,
                    record.doi,
                    record.study_design,
                    record.population,
                    record.abstract_like_summary,
                ),
            )

            for order, author in enumerate(record.authors, start=1):
                connection.execute(
                    "INSERT INTO paper_authors (paper_id, author_order, author_name) VALUES (?, ?, ?)",
                    (paper_id, order, author),
                )
            for diagnosis in record.diagnoses:
                connection.execute(
                    "INSERT INTO paper_diagnoses (paper_id, diagnosis) VALUES (?, ?)",
                    (paper_id, diagnosis),
                )
            for modality in record.modalities:
                connection.execute(
                    "INSERT INTO paper_modalities (paper_id, modality) VALUES (?, ?)",
                    (paper_id, modality),
                )
            for roi in record.rois:
                connection.execute(
                    "INSERT INTO paper_rois (paper_id, roi_name) VALUES (?, ?)",
                    (paper_id, roi),
                )

            diagnosis_scope = record.diagnoses or [None]
            for symptom in record.symptoms:
                for diagnosis in diagnosis_scope:
                    connection.execute(
                        """
                        INSERT INTO paper_symptoms (paper_id, diagnosis, symptom, evidence_note)
                        VALUES (?, ?, ?, ?)
                        """,
                        (paper_id, diagnosis, symptom, record.title),
                    )

            roi_scope = record.rois or [None]
            metric_scope = record.imaging_metrics or [None]
            sex_scope = record.sex_scope or [None]
            for diagnosis in diagnosis_scope:
                for roi in roi_scope:
                    for metric in metric_scope:
                        if roi is None and metric is None:
                            continue
                        for sex in sex_scope:
                            connection.execute(
                                """
                                INSERT INTO roi_observations (
                                    paper_id,
                                    diagnosis,
                                    sex_scope,
                                    data_level,
                                    roi_name,
                                    imaging_metric,
                                    statistic_type,
                                    value_numeric,
                                    unit,
                                    n_total,
                                    evidence_note
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    paper_id,
                                    diagnosis,
                                    sex,
                                    "group_summary",
                                    roi,
                                    metric,
                                    "qualitative_pattern",
                                    None,
                                    None,
                                    None,
                                    record.title,
                                ),
                            )

            for finding in record.findings:
                connection.execute(
                    "INSERT INTO paper_findings (paper_id, finding_type, finding_text) VALUES (?, ?, ?)",
                    (paper_id, "finding", finding),
                )
            for limitation in record.limitations:
                connection.execute(
                    "INSERT INTO paper_findings (paper_id, finding_type, finding_text) VALUES (?, ?, ?)",
                    (paper_id, "limitation", limitation),
                )

        connection.commit()


def write_excel(records: list[LiteratureRecord], output_path: Path) -> None:
    if Workbook is None:
        raise ModuleNotFoundError("openpyxl is not installed in this environment")

    wb = Workbook()
    ws = wb.active
    ws.title = "papers"
    ws.append(
        [
            "source_label",
            "title",
            "year",
            "doi",
            "study_design",
            "population",
            "diagnoses",
            "modalities",
            "rois",
            "symptoms",
            "sex_scope",
            "imaging_metrics",
            "findings",
            "limitations",
            "source_type",
            "source_path_or_url",
            "extraction_mode",
        ]
    )

    for record in records:
        ws.append(
            [
                record.source_label,
                record.title,
                record.year,
                record.doi,
                record.study_design,
                record.population,
                "; ".join(record.diagnoses),
                "; ".join(record.modalities),
                "; ".join(record.rois),
                "; ".join(record.symptoms),
                "; ".join(record.sex_scope),
                "; ".join(record.imaging_metrics),
                " | ".join(record.findings),
                " | ".join(record.limitations),
                record.source_type,
                record.source_path_or_url,
                record.extraction_mode,
            ]
        )

    symptom_ws = wb.create_sheet("symptom_evidence")
    symptom_ws.append(["paper_title", "diagnosis", "symptom", "doi", "source_type"])
    for record in records:
        diagnoses = record.diagnoses or [None]
        if record.symptoms:
            for diagnosis in diagnoses:
                for symptom in record.symptoms:
                    symptom_ws.append([record.title, diagnosis, symptom, record.doi, record.source_type])

    vertical_ws = wb.create_sheet("roi_vertical_dataset")
    vertical_ws.append(
        [
            "paper_title",
            "doi",
            "diagnosis",
            "sex_scope",
            "data_level",
            "roi_name",
            "imaging_metric",
            "statistic_type",
            "value_numeric",
            "unit",
            "n_total",
            "evidence_note",
        ]
    )
    for record in records:
        diagnoses = record.diagnoses or [None]
        rois = record.rois or [None]
        metrics = record.imaging_metrics or [None]
        sexes = record.sex_scope or [None]
        for diagnosis in diagnoses:
            for roi in rois:
                for metric in metrics:
                    if roi is None and metric is None:
                        continue
                    for sex in sexes:
                        vertical_ws.append(
                            [
                                record.title,
                                record.doi,
                                diagnosis,
                                sex,
                                "group_summary",
                                roi,
                                metric,
                                "qualitative_pattern",
                                None,
                                None,
                                None,
                                record.title,
                            ]
                        )

    wb.save(output_path)


def analyze_sources(
    inputs: list[str],
    output_dir: str | Path = "literature_outputs",
    ai_backend: str = "none",
    ai_base_url: str | None = None,
    ai_model: str | None = None,
    ai_api_key: str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[LiteratureRecord] = []
    source_docs: list[SourceDocument] = []
    effective_ai_backend = ai_backend
    effective_ai_base_url = ai_base_url
    effective_ai_model = ai_model

    if ai_backend == "auto":
        detected_base, detected_model = detect_openai_compatible_endpoint()
        if detected_base and detected_model:
            effective_ai_backend = "openai_compatible"
            effective_ai_base_url = detected_base
            effective_ai_model = detected_model
        else:
            effective_ai_backend = "none"

    for input_value in inputs:
        doc = load_source(input_value)
        source_docs.append(doc)
        if effective_ai_backend == "openai_compatible":
            if not effective_ai_base_url or not effective_ai_model:
                raise ValueError("ai_base_url and ai_model are required when ai_backend='openai_compatible'")
            record = ai_record(doc, effective_ai_base_url, effective_ai_model, ai_api_key)
        else:
            record = heuristic_record(doc)
        records.append(clean_record(record))

    sql_path = output_dir / "literature_database.sql"
    sqlite_path = output_dir / "literature_database.sqlite"
    json_path = output_dir / "literature_database.json"
    xlsx_path = output_dir / "literature_database.xlsx"

    sql_path.write_text(build_sql(records), encoding="utf-8")
    write_sqlite(records, sqlite_path)
    json_path.write_text(
        json.dumps([record.__dict__ for record in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    xlsx_written = False
    if Workbook is not None:
        write_excel(records, xlsx_path)
        xlsx_written = True

    return {
        "records": [record.__dict__ for record in records],
        "sql_path": str(sql_path.resolve()),
        "sqlite_path": str(sqlite_path.resolve()),
        "json_path": str(json_path.resolve()),
        "xlsx_path": str(xlsx_path.resolve()) if xlsx_written else None,
        "sources": [doc.input_value for doc in source_docs],
        "effective_ai_backend": effective_ai_backend,
        "effective_ai_base_url": effective_ai_base_url,
        "effective_ai_model": effective_ai_model,
    }


if __name__ == "__main__":
    demo_inputs = []
    if demo_inputs:
        result = analyze_sources(demo_inputs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Set demo_inputs or import analyze_sources(...) from a notebook.")
