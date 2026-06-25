from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd

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
    "posterior cingulate": "posterior cingulate cortex",
    "posterior cingulate cortex": "posterior cingulate cortex",
    "inferior parietal": "inferior parietal cortex",
    "inferior parietal cortex": "inferior parietal cortex",
    "temporal cortex": "temporal cortex",
    "temporal lobe": "temporal cortex",
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
}

METRIC_ALIASES = {
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
        "parahippocampal gyrus": "parahippocampal gyrus",
        "posterior cingulate cortex": "posterior cingulate cortex",
        "inferior parietal cortex": "inferior parietal cortex",
        "temporal cortex": "temporal cortex",
        "frontal cortex": "frontal cortex",
        "anterior temporal cortex": "anterior temporal cortex",
        "insula": "insula",
        "anterior cingulate cortex": "anterior cingulate cortex",
        "white matter": "white matter",
    }
    if value in exact_aliases:
        return exact_aliases[value]

    for alias, canonical in ROI_ALIASES.items():
        if alias in value:
            return canonical
    return WHITESPACE_RE.sub(" ", str(label)).strip()


def normalize_metric_label(label: Any) -> str:
    value = WHITESPACE_RE.sub(" ", str(label)).strip().lower()
    if not value or value == "none":
        return ""

    exact_aliases = {
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
    for raw_record in records:
        if isinstance(raw_record, LiteratureRecord):
            record = raw_record
        else:
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

        diagnoses = record.diagnoses or [None]
        rois = record.rois or [None]
        metrics = record.imaging_metrics or [None]
        for diagnosis in diagnoses:
            for roi in rois:
                for metric in metrics:
                    rows.append(
                        {
                            "diagnosis": diagnosis,
                            "diagnosis_normalized": normalize_diagnosis_label(diagnosis) if diagnosis else None,
                            "roi_name": roi,
                            "roi_name_normalized": normalize_roi_label(roi) if roi else None,
                            "imaging_metric": metric,
                            "imaging_metric_normalized": normalize_metric_label(metric) if metric else None,
                            "pattern_summary": " | ".join(record.findings or []),
                            "source_title": record.title,
                            "doi": record.doi,
                            "source_type": record.source_type,
                            "study_design": record.study_design,
                            "modalities": "; ".join(record.modalities or []),
                            "limitations": " | ".join(record.limitations or []),
                        }
                    )
    return pd.DataFrame(rows)


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
    return out


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


def compare_features_to_literature(
    structural_df: pd.DataFrame,
    evidence_df: pd.DataFrame,
    diagnosis: str | None = None,
    subject_id: str | None = None,
    roi: str | None = None,
    metric: str | None = None,
) -> pd.DataFrame:
    patient_rows = query_structural_features(structural_df, subject_id=subject_id, diagnosis=diagnosis, roi=roi, metric=metric)
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
        if diagnosis is not None:
            matches = matches[matches["diagnosis_normalized"].astype(str).str.lower() == normalize_diagnosis_label(diagnosis).lower()]
        elif pd.notna(row.get("diagnosis_normalized")):
            matches = matches[matches["diagnosis_normalized"].astype(str).str.lower() == str(row["diagnosis_normalized"]).lower()]
        if pd.notna(row.get("roi_name_normalized")):
            matches = matches[matches["roi_name_normalized"].astype(str).str.lower() == str(row["roi_name_normalized"]).lower()]
        if pd.notna(row.get("imaging_metric_normalized")):
            matches = matches[matches["imaging_metric_normalized"].astype(str).str.lower() == str(row["imaging_metric_normalized"]).lower()]

        if matches.empty:
            merged_rows.append(
                {
                    "subject_id": row.get("subject_id"),
                    "diagnosis": row.get("diagnosis_normalized"),
                    "roi_name": row.get("roi_name_normalized"),
                    "imaging_metric": row.get("imaging_metric_normalized"),
                    "value_numeric": row.get("value_numeric"),
                    "evidence_match": False,
                    "source_title": None,
                    "pattern_summary": None,
                    "limitations": None,
                }
            )
            continue

        for _, match in matches.iterrows():
            merged_rows.append(
                {
                    "subject_id": row.get("subject_id"),
                    "diagnosis": row.get("diagnosis_normalized"),
                    "roi_name": row.get("roi_name_normalized"),
                    "imaging_metric": row.get("imaging_metric_normalized"),
                    "value_numeric": row.get("value_numeric"),
                    "evidence_match": True,
                    "source_title": match.get("source_title"),
                    "pattern_summary": match.get("pattern_summary"),
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
    diagnosis_candidates: list[str] | None = None,
) -> pd.DataFrame:
    structural = query_structural_features(structural_df, subject_id=subject_id)
    evidence_df = build_evidence_framework(records)
    if structural.empty:
        return pd.DataFrame()

    if diagnosis_candidates is None:
        diagnosis_candidates = sorted(set(DIAGNOSIS_SIGNATURES) | set(evidence_df.get("diagnosis_normalized", pd.Series(dtype=str)).dropna().tolist()))

    summary_rows = []
    for diagnosis in diagnosis_candidates:
        diagnosis_norm = normalize_diagnosis_label(diagnosis)
        row_scores = structural.apply(lambda row: score_structural_match_for_diagnosis(row, diagnosis_norm), axis=1)
        structural_score = int(row_scores.sum())
        signature_hits = int((row_scores > 0).sum())

        evidence_matches = compare_features_to_literature(structural, evidence_df, diagnosis=diagnosis_norm)
        literature_score = int(evidence_matches["evidence_match"].sum()) if not evidence_matches.empty else 0
        source_titles = []
        if not evidence_matches.empty and "source_title" in evidence_matches.columns:
            source_titles = dedupe_strings([str(x) for x in evidence_matches["source_title"].dropna().tolist()])[:5]

        summary_rows.append(
            {
                "diagnosis": diagnosis_norm,
                "structural_signature_score": structural_score,
                "signature_hit_rows": signature_hits,
                "literature_match_rows": literature_score,
                "combined_support_score": structural_score + literature_score,
                "example_sources": " | ".join(source_titles),
            }
        )

    out = pd.DataFrame(summary_rows)
    if not out.empty:
        out = out.sort_values(["combined_support_score", "literature_match_rows", "structural_signature_score"], ascending=False).reset_index(drop=True)
    return out


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
            "## Literature-Linked Evidence",
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
    json_path = output_dir / "literature_database.json"
    xlsx_path = output_dir / "literature_database.xlsx"

    sql_path.write_text(build_sql(records), encoding="utf-8")
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
