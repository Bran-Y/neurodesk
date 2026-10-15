"""Isolated QC-unfiltered sensitivity comparison; never releases an active hold."""
import argparse
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


SUBJECTS = ('PPMI_41282', 'PPMI_41289', 'PPMI_41293')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unfiltered_copy(features):
    # Recalculate from measured values, not from QC-cleared prediction columns.
    return features.drop(columns=['qc_hold_reason'], errors='ignore').copy(deep=True)


def metadata(folder):
    records, sources = {}, []
    for path in sorted(folder.rglob('*.xml')):
        tree = ET.parse(path).getroot()
        for element in tree.iter():
            element.tag = element.tag.rsplit('}', 1)[-1]
        subject = tree.find('project/subject')
        if subject is None:
            subject = tree.find('subject')
            image = tree.find('image')
            if tree.tag != 'metadata' or subject is None or image is None:
                raise ValueError('No subject metadata: ' + str(path))
            sources.append(dict(path=str(path), sha256=digest(path),
                                subject_id='PPMI_' + subject.get('id'),
                                image_uid=image.get('uid').removeprefix('I'),
                                record_type='identifier_only'))
            continue
        terms = {p.get('term'): p.text for p in subject.findall('study/imagingProtocol/protocolTerm/protocol')}
        record = dict(subject_id='PPMI_' + subject.findtext('subjectIdentifier'),
                      recorded_research_group=subject.findtext('researchGroup'),
                      sex=subject.findtext('subjectSex'), age=subject.findtext('study/subjectAge'),
                      visit=subject.findtext('visit/visitIdentifier'),
                      date_acquired=subject.findtext('study/series/dateAcquired'),
                      series_id=subject.findtext('study/series/seriesIdentifier'),
                      image_uid=subject.findtext('study/imagingProtocol/imageUID'),
                      protocol_terms=terms,
                      assessments=[dict(instrument=a.get('name'), attribute=v.get('attribute'), value=v.text)
                                   for a in subject.findall('visit/assessment') for v in a.iter('assessmentScore')])
        key = (record['subject_id'], record['image_uid'])
        if key in records and records[key] != record:
            raise ValueError('Conflicting duplicate metadata: ' + str(key))
        records[key] = record
        sources.append(dict(path=str(path), sha256=digest(path), subject_id=key[0], image_uid=key[1]))
    if any((s['subject_id'], s['image_uid']) not in records for s in sources):
        raise ValueError('Identifier-only XML has no corresponding detailed record')
    return dict(records=list(records.values()), sources=sources,
                unique_scan_records=len(records), xml_files=len(sources),
                scope='Recorded research cohort and acquisition metadata only; no clinical diagnosis inferred.',
                missing_clinical_fields=['HY stage', 'UPDRS', 'DATscan', 'medication', 'disease duration', 'MoCA'])


def page(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + html.escape(title) + '</title><style>'
            'body{font-family:Georgia,serif;max-width:1250px;margin:36px auto;padding:0 24px;color:#183038}'
            'h1,h2,h3{font-family:sans-serif}table{border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px}'
            'td,th{padding:10px;text-align:left;border-bottom:1px solid #ccc}section{margin:30px 0}'
            '.notice{background:#fff3da;padding:18px}.scroll{overflow:auto}a{color:#126476}</style>'
            '<body><h1>' + html.escape(title) + '</h1>' + body + '</body></html>')


def write_metadata(folder, output):
    data = metadata(folder)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'source_metadata.json').write_text(json.dumps(data, indent=2) + '\n')
    body = ('<p>' + html.escape(data['scope']) + '</p><p>' + str(data['xml_files']) +
            ' XML files contain ' + str(data['unique_scan_records']) + ' unique scan records for ' +
            str(len({r['subject_id'] for r in data['records']})) +
            ' subjects. Nested XMLs are identifier-only records, not additional clinical observations. '
            'No image volumes or clinical case report forms were supplied.</p>')
    for row in data['records']:
        terms = row['protocol_terms']
        body += '<section><h2>' + html.escape(row['subject_id']) + ' / I' + html.escape(row['image_uid']) + '</h2><p>'
        body += html.escape(f"Recorded cohort: {row['recorded_research_group']}; sex: {row['sex']}; age at scan: {row['age']}; visit: {row['visit']}; acquired: {row['date_acquired']}") + '</p><p>'
        body += html.escape('Scanner: ' + str(terms.get('Manufacturer')) + ' ' + str(terms.get('Mfg Model')) + '; field strength as recorded: ' + str(terms.get('Field Strength'))) + '</p>'
        if terms.get('Field Strength') == '0.0':
            body += '<p class="notice">Field strength 0.0 is incomplete metadata, not evidence of a physical 0T scanner. Do not substitute values from a different image UID.</p>'
        body += '<p>Assessment values as recorded: ' + html.escape(json.dumps(row['assessments'])) + '. These are not used as HY stage or diagnostic evidence.</p></section>'
    body += '<p>Unavailable clinical fields: ' + html.escape(', '.join(data['missing_clinical_fields'])) + '.</p><p><a href="source_metadata.json">Source metadata and file hashes</a></p>'
    (output / 'SOURCE_METADATA.html').write_text(page('PPMI original metadata verification', body))
    print(json.dumps(data, indent=2))


def run(root, output):
    import pandas as pd
    from finished_evidence_workflow import resolve_required_files
    from mmc_normative_workflow import evaluate_features, load_models
    from pd_evidence import compare_result, compare_stage_result
    from possible_disease_interpretation import summarize
    from pd_pattern_profile import render as render_profile
    from potvin_subcortical import augment_normative

    resources = resolve_required_files(root)
    pack = load_models(resources['mmc_models'])
    protected = list((root / 'outputs/segmentation_qc').rglob('*.json'))
    protected += list((root / 'outputs/segmentation_holds').rglob('*.json'))
    selected = {}
    for sid in SUBJECTS:
        manifests = sorted((root / 'outputs' / sid).rglob('workflow_run_manifest.json'))
        complete = [p for p in manifests if (p.parent / 'atlas_translation_audit.csv').is_file()
                    and (p.parent / 'normative_roi_results.csv').is_file()]
        if not complete:
            raise ValueError('No complete feature export for ' + sid)
        selected[sid] = complete[-1]
        protected += [complete[-1], complete[-1].parent / 'atlas_translation_audit.csv',
                      complete[-1].parent / 'normative_roi_results.csv']
    before = {str(p): digest(p) for p in protected}
    output.mkdir(parents=True, exist_ok=False)
    summaries, provenance, sections = [], [], []
    for sid, manifest in selected.items():
        parent = manifest.parent
        original = pd.read_csv(parent / 'atlas_translation_audit.csv')
        if set(original.subject_id) != {sid}:
            raise ValueError('Subject identity mismatch')
        saved = pd.read_csv(parent / 'normative_roi_results.csv')
        baseline = compare_result(dict(project_dir=root, comparison_features=original, normative=saved), sid)
        features = unfiltered_copy(original)
        norms = evaluate_features(features, pack)
        result = dict(project_dir=root, comparison_features=features, normative=norms)
        norms = augment_normative(result, norms)
        result['normative'] = norms
        rows = compare_result(result, sid)
        stages = compare_stage_result(result, sid)
        interpretation = summarize(pd_rows=rows, scope='PD')
        detail = pd.DataFrame(rows)
        detail['qc_policy_applied'] = False
        detail['measurement_validation'] = 'Unconfirmed: QC holds ignored for sensitivity analysis only'
        summary = dict(subject_id=sid, reference_features=len(rows),
                       matched_with_qc=sum(r['match_status'] == 'matched_for_context' for r in baseline),
                       matched_without_qc=sum(r['match_status'] == 'matched_for_context' for r in rows),
                       with_available_interval=sum(r['normative_status'] in ('within_95pi', 'below_95pi', 'above_95pi') for r in rows),
                       outside_pi=sum(r['normative_status'] in ('below_95pi', 'above_95pi') for r in rows),
                       pd_like_directional_features=len(interpretation['pd']['reasons']),
                       directional_profile_assessed=interpretation['pd']['directional_profile']['assessed'],
                       directional_profile_aligned=len(interpretation['pd']['directional_profile']['aligned']),
                       directional_profile_opposed=len(interpretation['pd']['directional_profile']['opposed']),
                       significant_opposite_direction_features=len(interpretation['pd']['opposing_features']),
                       normative_models_calculated=int(norms.calculation_status.eq('calculated').sum()),
                       qc_policy_applied=False, assigned_diagnosis=None)
        summaries.append(summary)
        provenance.append(dict(subject_id=sid, input_manifest=str(manifest), input_sha256=before[str(manifest)],
                               interpretation=interpretation,
                               retained_holds=sorted(set(original.get('qc_hold_reason', pd.Series(dtype=str)).dropna()) - {''})))
        detail.to_csv(output / (sid + '_enigma_comparisons.csv'), index=False)
        norms.to_csv(output / (sid + '_recomputed_normative.csv'), index=False)
        pd.DataFrame(stages).assign(qc_policy_applied=False).to_csv(output / (sid + '_hy_sensitivity.csv'), index=False)
        cols = ['source_structure', 'hemisphere', 'metric', 'measured', 'unit', 'expected_value',
                'lower_95pi', 'upper_95pi', 'normative_status', 'pd_minus_control_cohen_d', 'p_as_reported', 'context']
        outliers = detail[detail.normative_status.isin(['below_95pi', 'above_95pi'])]
        sections.append('<section><h2>' + sid + '</h2><p>' + html.escape(interpretation['conclusion']) + '</p>'
                        + render_profile(interpretation['pd']['directional_profile'])
                        + '<p>Matching coverage: ' + str(summary['matched_without_qc']) + '/' + str(len(rows)) +
                        '. Available individual normative intervals: ' + str(summary['with_available_interval']) +
                        '. A matched group effect without an individual reference interval is not an assessed normal measurement.</p>'
                        '<p><a href="' + sid + '_enigma_comparisons.csv">All ENIGMA comparisons</a> | '
                        '<a href="' + sid + '_recomputed_normative.csv">Recomputed normative results</a> | '
                        '<a href="' + sid + '_hy_sensitivity.csv">HY-stratum sensitivity (no patient stage assigned)</a></p>'
                        '<h3>Features outside the pointwise normative interval</h3><div class="scroll">'
                        + (outliers[cols].fillna('Not available').to_html(index=False, escape=True, border=0)
                           if len(outliers) else '<p>None among available normative comparisons.</p>') + '</div>'
                        '<details><summary>View all matched ENIGMA measurements</summary><div class="scroll">'
                        + detail[cols].fillna('Not available').to_html(index=False, escape=True, border=0) + '</div></details></section>')
    after = {str(p): digest(p) for p in protected}
    if before != after:
        raise RuntimeError('Protected inputs changed during analysis; do not use this output')
    audit = dict(mode='exploratory_no_qc', created_utc=datetime.now(timezone.utc).isoformat(),
                 known_diagnosis_used_as_model_input=False, qc_status_modified=False,
                 protected_inputs_unchanged=True, protected_sha256=before, summaries=summaries, provenance=provenance)
    (output / 'analysis_manifest.json').write_text(json.dumps(audit, indent=2, default=str) + '\n')
    table = pd.DataFrame(summaries)[['subject_id', 'matched_with_qc', 'matched_without_qc',
                                     'with_available_interval', 'outside_pi', 'pd_like_directional_features',
                                     'directional_profile_assessed', 'directional_profile_aligned', 'directional_profile_opposed']].rename(columns={
        'subject_id': 'Subject', 'matched_with_qc': 'Matched with QC holds',
        'matched_without_qc': 'Matched without QC holds', 'with_available_interval': 'Available intervals',
        'outside_pi': 'Outside interval', 'pd_like_directional_features': 'Outside-PI concordant',
        'directional_profile_assessed': 'Pattern metrics assessed',
        'directional_profile_aligned': 'Same direction',
        'directional_profile_opposed': 'Opposite direction'}).to_html(index=False, border=0)
    notice = ('<p class="notice"><b>Exploratory comparison: QC holds were not applied.</b> '
              'Measurements remain unconfirmed; original QC status is unchanged. '
              'This is a sensitivity result, not QC approval or an assigned diagnosis.</p>'
              '<p>ENIGMA supplies PD-versus-Control group effect sizes, not an individual normal range. '
              'Intervals below come from compatible Potvin healthy-cohort models. Matching published effect direction '
              'is descriptive only; nominal source p values and pointwise intervals are not multiplicity-corrected. '
              'All published HY strata are exported separately; no patient HY stage is inferred. '
              'Atlas, version, unit and source-conflict checks remain active. No known cohort label is used to force a match.</p>')
    (output / 'EXPLORATORY_PD_NO_QC.html').write_text(page('PPMI ENIGMA comparison without QC holds', notice + '<div class="scroll">' + table + '</div>' + ''.join(sections) + '<p><a href="analysis_manifest.json">Analysis provenance and protected-file hashes</a></p>'))
    print(json.dumps(dict(output=str(output), summaries=summaries, protected_inputs_unchanged=True), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--metadata-folder', type=Path)
    args = parser.parse_args()
    if args.metadata_folder:
        write_metadata(args.metadata_folder, args.output)
    else:
        run(args.root.resolve(), args.output.resolve())
