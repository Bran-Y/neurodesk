"""Source-bound assistant observations and a reproducible presentation-only audit."""
from collections import Counter
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import zipfile

DATE = '2026-10-04'
FOLDER = 'outputs/pending_review_20261004'
OAS_NOTES = {
    'OAS1_0003_MR1': 'Broad white/pial alignment and ventricular labels within visible CSF spaces. No gross global offset in sampled views.',
    'OAS1_0004_MR1': 'Broad cortical and deep-label alignment. Check irregular inferior mask edge near coronal 104 on adjacent native slices.',
    'OAS1_0005_MR1': 'Broad cortical alignment. Small mask speckles in sagittal 127 and ragged inferior edges in coronal 110/153 need adjacent unmasked-original comparison; tissue loss is not established.',
    'OAS1_0006_MR1': 'Broad cortical alignment. Ragged/broken inferior mask coverage near coronal 105/140 needs adjacent original comparison; this is not an automatic failure.',
    'OAS1_0015_MR1': 'Broad white/pial alignment and ventricular labels in visible CSF. Scattered mask speckles and inferior coronal 105 edge need adjacent original comparison; no gross global offset.',
    'OAS1_0022_MR1': 'Broad surface/deep-label alignment; mask follows visible brain outline. Small superior/peripheral mask gaps near sagittal 97 and inferior coronal 110 require native-slice inspection.',
    'OAS1_0028_MR1': 'Broad surface/deep-label alignment and ventricular CSF coverage. Inferior coronal 106/144 mask edges require adjacent original inspection.',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Presentation(HTMLParser):
    """Count explanatory paragraphs visible before closed details are expanded."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.details = []
        self.suppressed = 0
        self.paragraph = None
        self.visible = []
        self.all_paragraphs = []
        self.detail_balance = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            self.details.append('open' in dict(attrs))
            self.detail_balance += 1
        if tag in ('script', 'style'):
            self.suppressed += 1
        if tag == 'p':
            self.paragraph = [not self.suppressed and all(self.details), []]

    def handle_endtag(self, tag):
        if tag == 'details':
            if not self.details:
                raise ValueError('Unmatched details closure')
            self.details.pop()
            self.detail_balance -= 1
        if tag in ('script', 'style'):
            self.suppressed = max(0, self.suppressed - 1)
        if tag == 'p' and self.paragraph is not None:
            visible, parts = self.paragraph
            value = ' '.join(''.join(parts).split())
            if value:
                self.all_paragraphs.append(value)
                if visible:
                    self.visible.append(value)
            self.paragraph = None

    def handle_data(self, data):
        if self.paragraph is not None and not self.suppressed:
            self.paragraph[1].append(data)


def presentation(content):
    parser = Presentation()
    parser.feed(content)
    parser.close()
    if parser.details or parser.detail_balance:
        raise ValueError('Unclosed details section')
    counts = Counter(parser.visible)
    return dict(visible_paragraphs=len(parser.visible),
        visible_explanation_words=sum(len(text.split()) for text in parser.visible),
        total_paragraphs=len(parser.all_paragraphs),
        duplicate_visible_paragraphs=[text for text, n in counts.items() if n > 1],
        empty_optional_fields=any('MMSE: N/A' in p or 'CDR: N/A' in p for p in parser.visible),
        empty_pending_note=any(re.search(r'pending_visual_review\s*:$', p) for p in parser.visible))


def sampled_records(root, cases):
    from report_quality import source_fingerprint
    from segmentation_viewer import save_boundary_montages
    old_path = root / 'outputs/assistant_visual_review_20261003/observations.json'
    old = {row['subject_id']: row for row in json.loads(old_path.read_text())['subjects']}
    records = []
    for sid, note in OAS_NOTES.items():
        if sid not in cases:
            continue
        fs_root = cases[sid]['subjects_dir']
        source, missing = source_fingerprint(fs_root, sid)
        _, manifest = save_boundary_montages(fs_root, sid, root / 'outputs/segmentation_overlay_cache')
        previous = old[sid]
        if missing or manifest['source_sha256'] != previous['boundary_source_sha256']:
            raise ValueError('Viewed montage source changed: ' + sid)
        for item in previous['images']:
            if digest(root / item['relative_path']) != item['sha256']:
                raise ValueError('Viewed image changed: ' + sid)
        records.append(dict(subject_id=sid, source_fingerprint=source,
            reviewer_role='assistant', human_qc_accepted=False, reviewed_at=DATE,
            status='sampled_review_complete_human_qc_pending',
            scope=previous['scope'], slices_per_plane=previous['slices_per_plane'],
            images=previous['images'], summary=note,
            checks=[dict(check='Sampled brain mask, white/pial surfaces and selected aseg labels',
                assessment='Sampled observation only', observation=note,
                action='Inspect adjacent native slices, motion and small-structure boundaries before human sign-off.')]))
    return records


def pending_dispositions(root, out):
    from literature_audit import build_literature_audit
    audit = build_literature_audit(root, out / 'literature')
    evidence = audit['evidence']
    pending = evidence.loc[~evidence.manual_review_status.isin(['accepted', 'rejected'])]
    pending.to_csv(out / 'active_evidence_review_queue.csv', index=False)
    approvals_path = root / 'workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json'
    approvals = json.loads(approvals_path.read_text())
    accepted = [p['doi'] for p in approvals['papers'] if p.get('human_review_status') == 'accepted'
                and p.get('data_use_status') == 'user_approved_research_use']
    record = dict(reviewed_at=DATE, reviewer_role='assistant',
        active_evidence_rows=len(evidence), active_pending_rows=len(pending),
        catalog_scope='Main literature_audit catalog only; ENIGMA and additional PD stores are counted separately.',
        accepted_additional_pd_papers=accepted, paper_approval_sha256=digest(approvals_path),
        human_patient_qc_inferred=False, field_concordance_inferred=False,
        dispositions=[
            dict(item='ENIGMA separate source store: 152 whole-sample + 608 HY-stage rows',
                 status='assistant_technical_review_complete_human_row_flags_retained',
                 action='PDF extraction rechecked separately; 6 whole-sample field differences and 1 HY-stage sign conflict remain withheld. Same-parser extraction is not independent human concordance. See enigma_source_technical_review.json.'),
            dict(item='Historical/raw pending flags', status='superseded_by_explicit_paper_authorisation',
                 action='Use the existing paper approval manifest; preserve original import/history flags. Paper approval does not imply field concordance or patient QC.'),
            dict(item='ENIGMA S3c vs S4l: left lateral ventricle HY4-5',
                 status='published_sign_discrepancy_confirmed_by_assistant',
                 evidence='Supplement PDF page 11 S3c d=-0.357; page 25 S4l d=+0.357, b=2761.46.',
                 pdf_sha256='076e783485824d61d168958060e9d4188d68393d615e4275b03c38b5fea4a2a1',
                 action='Retain both source values; direction remains withheld. No guessed correction or human acceptance.'),
            dict(item='Hanganu SD printed 8,46', status='source_format_supported_by_user_screenshot',
                 action='Preserve raw 8,46 and parsed 8.46 with provenance; no new human signature.'),
            dict(item='Hanganu mean change -43.67 vs +1.40%', status='unresolved_published_sign_question',
                 action='Keep both verbatim, do not use percentage direction as independent disease evidence. Full original/author clarification required.'),
            dict(item='Figure-level FDR/a-priori uncorrected status and correlation stars',
                 status='per_roi_corrected_status_not_established',
                 action='Do not mark every named ROI corrected. Obtain per-cluster output or explicit figure legend assignment.'),
            dict(item='Single-scan vs longitudinal, log-volume and pial-area definitions',
                 status='methodological_limit_not_an_approval_queue',
                 action='Leave ineligible comparisons withheld until required data/definitions exist.')])
    (out / 'pending_dispositions.json').write_text(json.dumps(record, indent=2))
    return record


def latest_report(root, sid):
    snapshot = root / 'pending_report_snapshot_20261004.zip'
    if snapshot.is_file():
        with zipfile.ZipFile(snapshot) as bundle:
            suffix = '/concise_reports/' + sid + '_concise_report.html'
            matches = [name for name in bundle.namelist() if name.endswith(suffix)]
        if len(matches) == 1 and (root / matches[0]).is_file():
            return root / matches[0]
    paths = list((root / 'outputs').glob('**/concise_reports/' + sid + '_concise_report.html'))
    return max(paths, key=lambda p: p.stat().st_mtime_ns) if paths else None


def compare_numeric(old, new):
    import pandas as pd
    checks = []
    prose_updates = []
    if old is None:
        return checks, prose_updates
    for previous in sorted(old.parent.glob('*')):
        if previous.suffix not in ('.csv', '.json'):
            continue
        current = new.parent / previous.name
        if not current.is_file():
            raise ValueError('Export disappeared: ' + previous.name)
        if previous.suffix == '.csv':
            before, after = pd.read_csv(previous), pd.read_csv(current)
            added = set(after.columns) - set(before.columns)
            if set(before.columns) - set(after.columns) or added - {'corrected_significance_status', 'nominal_p_below_0_05'}:
                raise ValueError('Unexpected export schema change: ' + previous.name)
            if added:
                prose_updates.append(dict(file=previous.name, added_statistical_metadata_columns=sorted(added)))
                after = after[before.columns]
            # Context text was corrected in a previous code update; preserve that history separately.
            if 'context' in before and 'context' in after:
                changed = before.context.fillna('').ne(after.context.fillna(''))
                for index in before.index[changed]:
                    prose_updates.append(dict(file=previous.name, row=int(index),
                        before=str(before.at[index, 'context']), after=str(after.at[index, 'context'])))
                before = before.drop(columns='context')
                after = after.drop(columns='context')
            pd.testing.assert_frame_equal(before, after, check_dtype=False, check_exact=True)
        else:
            if json.loads(previous.read_text()) != json.loads(current.read_text()):
                raise ValueError('Interpretation changed: ' + previous.name)
        checks.append(previous.name)
    return checks, prose_updates


def run(root):
    from user_pipeline import read_config, participants, status, analyze
    from report_quality import read_qc
    from assistant_visual_review import detailed_record
    root = Path(root).resolve()
    out = root / FOLDER
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for path in sorted((root / 'cases').glob('*/config.json')):
        config = read_config(path)
        if config.get('modality', 'T1') != 'T1':
            continue
        for sid in participants(config).subject_id:
            if sid in cases:
                raise ValueError('Ambiguous duplicate case: ' + sid)
            cases[sid] = config
    observations = sampled_records(root, cases)
    (out / 'review_observations.json').write_text(json.dumps(dict(subjects=observations), indent=2))
    from review_enigma_source import review
    review(root, root / 'workflow_sources/Disease/PD/raw/mds28706-sup-0001-supinfo.pdf')
    dispositions = pending_dispositions(root, out)
    rows = []
    done_configs = {}
    for sid, config in cases.items():
        print('AUDIT', sid, flush=True)
        result_info = dict(project_dir=root, fs_root=config['subjects_dir'])
        qc_before = read_qc(result_info, sid)
        processing = next(row for row in status(config) if row['subject_id'] == sid)
        row = dict(subject_id=sid, processing=processing, human_qc_status=qc_before['status'])
        if not processing['complete']:
            row.update(report_status='blocked_processing_incomplete', next_action=processing['detail'])
        else:
            previous = latest_report(root, sid)
            before = presentation(previous.read_text()) if previous else None
            key = str(config['_path'])
            if key not in done_configs:
                done_configs[key] = analyze(config, root)
            result = done_configs[key]
            current = Path(result['output_dir']).parent / 'concise_reports' / (sid + '_concise_report.html')
            content = current.read_text()
            after = presentation(content)
            exports, prose_updates = compare_numeric(previous, current)
            if qc_before != read_qc(result_info, sid):
                raise ValueError('Human QC changed during presentation audit: ' + sid)
            if after['empty_optional_fields'] or after['empty_pending_note'] or after['duplicate_visible_paragraphs']:
                raise ValueError('Presentation defect remains: ' + sid)
            if 'AI-assisted disease discussion' in content or 'Generate AI report' in content:
                raise ValueError('AI report reintroduced')
            observation = detailed_record(result_info, sid)
            if observation is None or observation['status'] == 'stale_assistant_review':
                raise ValueError('No current source-bound assistant observations: ' + sid)
            row.update(report_status='refreshed_data_unchanged', before=before, after=after,
                numeric_exports_verified=exports, comparison_context_updates=prose_updates,
                report=str(current.relative_to(root)),
                assistant_review_status=observation['status'], assistant_review_date=observation['reviewed_at'],
                assistant_summary=observation['summary'], previous_report=str(previous.relative_to(root)) if previous else None)
        rows.append(row)
        (out / 'patient_report_audit.json').write_text(json.dumps(rows, indent=2))
    write_summary(root, out, rows, dispositions)
    print('DONE', len(rows), flush=True)


def write_summary(root, out, rows, dispositions):
    headers = ('Subject', 'Processing/report', 'Human QC', 'Visible explanation words before/after', 'Assistant findings')
    table = []
    for row in rows:
        values = [row['subject_id'], row['report_status'], row['human_qc_status'],
            str(row.get('before', {}).get('visible_explanation_words', '-')) + ' / ' + str(row.get('after', {}).get('visible_explanation_words', '-')),
            row.get('assistant_summary', row.get('next_action', ''))]
        cells = ''.join('<td>' + html.escape(value) + '</td>' for value in values)
        if row.get('report'):
            cells += '<td><a href="../../' + html.escape(row['report'], quote=True) + '">Open report</a></td>'
        table.append('<tr>' + cells + '</tr>')
    body = ('<!doctype html><meta charset="utf-8"><title>Pending review and report audit</title>'
        '<style>body{font:16px Georgia;max-width:1300px;margin:30px auto}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}table{width:100%;border-collapse:collapse}</style>'
        '<h1>Pending review and patient report audit</h1><p>2026-10-04 | Assistant technical review, not a human clinical/QC signature.</p>'
        '<p>Main literature catalog only: ' + str(dispositions['active_evidence_rows']) + '; pending: ' + str(dispositions['active_pending_rows']) +
        '. Existing additional PD paper approvals: ' + str(len(dispositions['accepted_additional_pd_papers'])) + '.</p>'
        '<p>Separate ENIGMA store: 760 raw human-review flags retained; assistant technical source check is recorded separately. Seven source-discrepant directions remain withheld.</p>'
        '<table><tr>' + ''.join('<th>' + value + '</th>' for value in headers) + '<th>Report</th></tr>' + ''.join(table) + '</table>'
        '<h2>Source and method review dispositions</h2>' + ''.join('<h3>' + html.escape(item['item']) + '</h3><p><b>' +
        html.escape(item['status']) + '</b></p><p>' + html.escape(item.get('evidence', '') + ' ' + item['action']) + '</p>'
        for item in dispositions['dispositions']))
    (out / 'PENDING_REVIEW_AND_REPORT_AUDIT.html').write_text(body)
    with zipfile.ZipFile(root / 'pending_review_results_20261004.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        files = list(out.rglob('*'))
        for row in rows:
            if row.get('report'):
                files.extend((root / row['report']).parent.glob('*'))
        for path in sorted(set(files)):
            if path.is_file():
                archive.write(path, path.relative_to(root))


if __name__ == '__main__':
    run(Path(__file__).parent)
