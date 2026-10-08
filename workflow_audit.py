"""Per-subject source coverage and native-atlas/version comparison provenance."""
import json
from pathlib import Path
import pandas as pd

ENIGMA_METHOD_URL = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8595579/'


def source_coverage(result, subject_id):
    from pd_evidence import compare_result, compare_stage_result
    from report_quality import source_contributions
    whole = pd.DataFrame(compare_result(result, subject_id))
    stages = pd.DataFrame(compare_stage_result(result, subject_id))
    papers = source_contributions(result['papers'], whole)
    papers['stage_reference_records'] = 0
    papers['matched_stage_features'] = 0
    papers['used_for_subject_qualitative'] = 0
    papers['paired_features_exploratory'] = 0
    papers['zero_match_reason'] = ''
    from pd_reviewed_comparison import coverage as reviewed_pd_coverage
    additional = reviewed_pd_coverage(result, subject_id)
    for _, item in additional.iterrows():
        selected_extra = papers.doi.eq(item.doi)
        if not selected_extra.any():
            papers = pd.concat([papers, pd.DataFrame([dict(paper_id='additional:' + item.doi,
                source_title=item.paper, doi=item.doi, unique_evidence_rows=0,
                reported_statistic_records=0, reported_statistics_scope='',
                connected_group_effect_records=0, matched_group_effect_features=0,
                stage_reference_records=0, matched_stage_features=0, used_for_subject_qualitative=0,
                paired_features_exploratory=0, zero_evidence_reason='', zero_match_reason='')])], ignore_index=True)
            selected_extra = papers.doi.eq(item.doi)
        papers.loc[selected_extra, 'additional_quantitative_records'] = item.reference_records
        papers.loc[selected_extra, 'additional_descriptive_comparisons'] = item.descriptive_comparisons
        papers.loc[selected_extra, 'additional_followup_required'] = item.followup_required
        papers.loc[selected_extra, 'zero_evidence_reason'] = ''
    links = result['links']
    if not links.empty:
        used = links.loc[links.subject_id.eq(subject_id)].groupby('paper_id').evidence_id.nunique()
        papers['used_for_subject_qualitative'] = papers.paper_id.map(used).fillna(0).astype(int)
    selected = papers.doi.eq('10.1002/mds.28706')
    if not stages.empty:
        papers.loc[selected, 'stage_reference_records'] = stages.evidence_id.nunique()
        papers.loc[selected, 'matched_stage_features'] = int(stages.match_status.eq('matched_for_context').sum())
    from reference_focus import pd_only
    path = Path(result['project_dir']) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
    if path.exists() and not pd_only(result):
        from comparison_atlas import comparison_features
        from zheng_exploratory import compare
        count = len(compare(comparison_features(result).to_dict('records'), json.loads(path.read_text()), subject_id)['features'])
        papers.loc[papers.doi.eq('10.1371/journal.pone.0279574'), 'paired_features_exploratory'] = count
    for index, paper in papers.iterrows():
        if pd.notna(paper.get('additional_quantitative_records')) and paper['additional_quantitative_records']:
            papers.loc[index, 'zero_match_reason'] = ('' if paper['additional_descriptive_comparisons'] else
                'Numeric tables are connected; longitudinal change, vertex clusters, log-volume or pial-area definition prevents a single-scan numeric difference')
            continue
        total = (paper['matched_group_effect_features'] + paper['matched_stage_features'] +
                 paper['used_for_subject_qualitative'] + paper['paired_features_exploratory'])
        if total:
            continue
        if paper.get('reported_statistic_records', 0):
            reason = paper['reported_statistics_scope']
        elif paper['connected_group_effect_records']:
            reason = 'Connected group references; patient atlas, hemisphere, metric, unit or version does not match'
        elif paper.get('method_records', 0) and not paper.get('quantitative_records', 0) and not paper.get('qualitative_records', 0):
            reason = 'Method/provenance context only; no regional patient comparison'
        elif not paper['unique_evidence_rows']:
            reason = 'Catalog entry only; no extracted evidence in a connected data store'
        elif not paper.get('human_accepted_rows', 0):
            reason = 'Extracted rows exist; none eligible for reviewed qualitative linking'
        else:
            reason = 'Extracted evidence exists; no eligible ROI/hemisphere/metric link for this patient'
        papers.loc[index, 'zero_match_reason'] = reason
    return papers


def atlas_comparisons(result, subject_id):
    from pd_evidence import compare_result
    rows = pd.DataFrame(compare_result(result, subject_id))
    columns = ['subject_id', 'source_structure', 'patient_roi_name', 'standard_roi_name',
               'hemisphere', 'metric', 'unit', 'patient_atlas', 'reference_atlas',
               'patient_processing_version', 'reference_processing_version', 'mapping_method',
               'match_status', 'context', 'source_table', 'source_page', 'evidence_id', 'doi']
    return rows[[column for column in columns if column in rows]].copy()


def method_compatibility(result, subject_id):
    from comparison_atlas import comparison_features
    features = comparison_features(result)
    features = features.loc[features.subject_id.eq(subject_id)]
    cortex = json.loads((Path(result['project_dir']) / 'workflow_sources/external_validators/mmc_dk_models.json').read_text())
    definitions = [
        ('Potvin cortical', cortex['doi'], 'dk_aparc', cortex['reference_freesurfer_version'],
         ('cortical_thickness', 'surface_area', 'roi_volume'), 'Individual covariate-adjusted prediction intervals',
         'workflow_sources/external_validators/mmc_dk_models.json'),
        ('Potvin subcortical', '10.1016/j.neuroimage.2016.05.016', 'freesurfer_aseg', '5.3',
         ('roi_volume',), 'Four eligible hippocampus/amygdala native-volume models',
         'workflow_sources/external_validators/potvin_subcortical_candidate.json'),
        ('ENIGMA PD cortical', '10.1002/mds.28706', 'dk_aparc', '5.3',
         ('cortical_thickness', 'surface_area'), 'Published PD-Control group effect; no individual reference interval',
         ENIGMA_METHOD_URL),
        ('ENIGMA PD subcortical', '10.1002/mds.28706', 'freesurfer_aseg', '5.3',
         ('roi_volume',), 'Published PD-Control group effect; no individual reference interval',
         ENIGMA_METHOD_URL)]
    output = []
    for name, doi, atlas, version, metrics, use, source in definitions:
        selected = features.loc[features.comparison_atlas_code.eq(atlas) & features.imaging_metric.isin(metrics)]
        versions = sorted(selected.processing_software_version.dropna().astype(str).unique())
        from processing_compatibility import all_versions_match
        ok = bool(len(selected)) and all_versions_match(selected.processing_software_version, version)
        output.append(dict(subject_id=subject_id, reference=name, doi=doi, reference_atlas=atlas,
            patient_versions=' | '.join(versions), reference_version=version,
            compatible_native_features=len(selected), version_compatible=ok,
            mapping='Native atlas identity and labels; no spatial atlas conversion',
            permitted_comparison=use, version_source=source,
            note='ENIGMA 2021 used FS5.3. FS8.2 is the separate T2 processing tool, not this paper reference.'))
    return pd.DataFrame(output)


def export_subject_audits(result, subject_id, output_dir):
    from cross_pipeline_review import subject_audit
    folder = Path(output_dir)
    for suffix, table in (('source_coverage', source_coverage(result, subject_id)),
                          ('atlas_comparisons', atlas_comparisons(result, subject_id)),
                          ('method_compatibility', method_compatibility(result, subject_id)),
                          ('cross_pipeline_review', subject_audit(result, subject_id))):
        table.to_csv(folder / f'{subject_id}_{suffix}.csv', index=False)
