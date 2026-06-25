# Neurodesk Literature To PostgreSQL Workflow

This repository contains a lightweight, shareable version of a Neurodesk workflow for:

- turning literature sources into a structured PostgreSQL-ready database
- querying disease-related evidence from literature records
- querying subject-level IPD ROI rows from an external vertical CSV dataset

The goal of this repo is to share the workflow itself without uploading generated databases or source datasets.

## Repository Contents

- `neurodesk_literature_to_pgsql.ipynb`: main workflow notebook for building and querying the literature/IPD workflow
- `neurodesk_literature_to_pgsql.py`: core extraction and export logic
- `.gitignore`: excludes generated database files, outputs, and local datasets

## Workflow Summary

1. Configure literature inputs as local PDFs and/or public URLs.
2. Run the extraction pipeline to build structured literature records.
3. Export generated outputs as:
   - `literature_database.sql`
   - `literature_database.json`
   - `literature_database.xlsx`
4. Load the external IPD ROI CSV table.
5. Demonstrate literature and IPD queries in the notebook.

## Data Sources

This workflow uses two external data sources. They are referenced in the notebook, but not committed to this repository.

### 1. Literature sources

Configured through the `INPUTS` list in the notebook.

Supported source types:

- local PDF files in the Neurodesk workspace
- public web pages
- PubMed / PMC article URLs

Examples shown in the notebook:

```python
INPUTS = [
    # '/home/jovyan/Desktop/paper.pdf',
    # 'https://pubmed.ncbi.nlm.nih.gov/32711083/',
    # 'https://pmc.ncbi.nlm.nih.gov/articles/PMC10406233/',
]
```

### 2. IPD ROI dataset

The notebook expects an external CSV at:

```text
/home/jovyan/oasis_selected/ipd_vertical_dataset/roi_vertical_dataset_template.csv
```

This file is treated as an external dataset input and is not uploaded here.

## Not Included In Git

The following are intentionally excluded:

- generated database artifacts such as `literature_database.sql`, `literature_database.json`, and `literature_database.xlsx`
- local output folders
- OASIS / IPD dataset files
- environment-specific caches and editor files

## Minimal Setup

Install the Python dependencies used by the workflow:

```bash
pip install pandas requests beautifulsoup4 pypdf openpyxl ipython
```

Then open the notebook and configure:

- `INPUTS`
- `OUTPUT_DIR`
- `LITERATURE_JSON_PATH`
- `IPD_CSV_PATH`

## Suggested GitHub Flow

```bash
git checkout -b V0.1
git add .
git commit -m "feat: add literature to pgsql workflow"
git push -u origin V0.1
```
