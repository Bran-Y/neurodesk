"""Presentation-only filtering for per-patient literature source tables."""
import pandas as pd


def include_extracted_library(papers, library):
    """Add library evidence without adding patient comparison counts."""
    current = papers.copy()
    fields = ('paper_id', 'doi', 'source_title', 'quantitative_records',
              'qualitative_records', 'method_records', 'reported_statistic_records',
              'unique_evidence_rows')
    for _, paper in library.iterrows():
        doi = str(paper.get('doi', '') or '').strip().lower()
        if doi and doi != 'nan':
            mask = current['doi'].fillna('').astype(str).str.strip().str.lower().eq(doi)
        else:
            mask = current['paper_id'].eq(paper.get('paper_id'))
        values = {key: paper[key] for key in fields if key in paper and pd.notna(paper[key])}
        if mask.any():
            for key, value in values.items():
                current.loc[mask, key] = value
        else:
            current = pd.concat([current, pd.DataFrame([values])], ignore_index=True)
    return current


def unified_numeric_sources(papers):
    """One catalog, retaining the distinction between extraction and comparison."""
    matched = patient_source_summary(papers)
    other = other_numeric_sources(papers)
    shown = papers.loc[papers.index.isin(matched.index) | papers.index.isin(other.index),
                       ['source_title', 'doi']].copy()
    labels = [('quantitative_records', 'registry numeric records'),
              ('additional_quantitative_records', 'reviewed PD table records'),
              ('connected_group_effect_records', 'PD group-effect records'),
              ('stage_reference_records', 'PD stage-reference records')]
    counts = papers.reindex(columns=[c for c, _ in labels]).apply(pd.to_numeric, errors='coerce').fillna(0)
    shown['extracted_numeric_evidence'] = [
        '; '.join(f'{int(counts.at[i, c])} {label}' for c, label in labels if counts.at[i, c] > 0)
        or 'See patient comparisons' for i in shown.index]
    shown['patient_comparisons'] = matched.patient_comparisons.reindex(shown.index).fillna('Not directly compared')
    return shown


def patient_numeric_sources(papers):
    """Show sources that contribute a numeric comparison for this patient."""
    counts = ('matched_group_effect_features', 'matched_stage_features',
              'paired_features_exploratory', 'additional_descriptive_comparisons')
    numeric = papers.reindex(columns=counts).apply(pd.to_numeric, errors='coerce').fillna(0)
    shown = papers.loc[numeric.gt(0).any(axis=1), ['source_title', 'doi']].copy()
    for column in counts:
        shown[column] = numeric.loc[shown.index, column].astype(int)
    return shown


def patient_source_summary(papers):
    """Compact view of the numeric comparisons actually used for this scan."""
    shown = patient_numeric_sources(papers)
    labels = (
        ('matched_group_effect_features', 'group-effect matches'),
        ('matched_stage_features', 'stage-context matches'),
        ('paired_features_exploratory', 'exploratory paired features'),
        ('additional_descriptive_comparisons', 'descriptive comparisons'),
    )
    result = shown[['source_title', 'doi']].copy()
    result['patient_comparisons'] = [
        '; '.join(f'{row[column]} {label}' for column, label in labels if row[column] > 0)
        for _, row in shown.iterrows()
    ]
    return result


def other_numeric_sources(papers):
    """Keep extracted numeric literature visible without implying a patient match."""
    labels = (
        ('quantitative_records', 'registry numeric records'),
        ('additional_quantitative_records', 'reviewed PD table records'),
        ('connected_group_effect_records', 'PD group-effect records'),
        ('stage_reference_records', 'PD stage-reference records'),
    )
    columns = [column for column, _ in labels]
    numeric = papers.reindex(columns=columns).apply(pd.to_numeric, errors='coerce').fillna(0)
    matched = patient_numeric_sources(papers).index
    context = papers.loc[numeric.gt(0).any(axis=1) & ~papers.index.isin(matched),
                         ['source_title', 'doi']].copy()
    context['extracted_numeric_evidence'] = [
        '; '.join(f'{int(numeric.at[index, column])} {label}'
                  for column, label in labels if numeric.at[index, column] > 0)
        for index in context.index
    ]
    return context
