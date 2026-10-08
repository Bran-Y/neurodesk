"""Traceable evidence catalog. Source indexes never become extracted evidence."""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd


def _read(path):
    if not path.exists():
        return []
    value = json.loads(path.read_text())
    return value if isinstance(value, list) else []


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def normalize_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*', '', str(value or '').strip(), flags=re.I).lower()


def build_literature_audit(project_dir, output_dir=None):
    root = Path(project_dir)
    src = root / 'workflow_sources'
    indexes = []
    for section in ('Disease', 'ROI'):
        for path in sorted((src / section).rglob('*.json')):
            if any(p.startswith('.') for p in path.parts):
                continue
            for i, row in enumerate(_read(path)):
                indexes.append((path.relative_to(root).as_posix(), i, row))
    extracted = []
    for filename, kind in [('quantitative_reference_statistics.json', 'group_distribution'),
                           ('method_evidence_statistics.json', 'method_evidence'),
                           ('reviewed_roi_evidence.json', 'regional_result'),
                           ('paper_reading_reviews/barnes_2005_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/barnes_2008_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/gutierrez_galve_2009_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/rohrer_2009_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/hippocampal_006_010_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/barnes_2010_covariate_reported_statistics.json', 'reported_statistics'),
                           ('paper_reading_reviews/zheng_2023_supplement_statistics.json', 'supplement_distribution')]:
        for i, row in enumerate(_read(src / filename)):
            extracted.append(('workflow_sources/' + filename, i, kind, row))
    review_path = 'workflow_sources/paper_reading_reviews/three_paper_review.json'
    for i, paper in enumerate(_read(root / review_path)):
        table2 = paper.get('table_2', {})
        for group, values in table2.get('mean_sd', {}).items():
            for j, (roi, pair) in enumerate(zip(table2.get('columns', []), values)):
                row = {key: paper.get(key) for key in ('paper_code', 'source_title', 'doi', 'year',
                       'source_url', 'human_review_status', 'approval_record')}
                row.update(diagnosis=group, roi_name=roi, hemisphere='bilateral',
                           imaging_metric=table2['metric'], unit=table2['unit'], mean=pair[0],
                           standard_deviation=pair[1], sample_size=paper.get('sample_size', {}).get(group),
                           source_location='Table 2; lobar values, not individual gyral ROI values',
                           extraction_method='Structured values from existing paper reading review',
                           comparison_compatible=False, evidence_note=table2.get('scope', ''))
                extracted.append((review_path, f'{i}/table_2/mean_sd/{group}/{j}', 'group_distribution', row))
    # DOI is authoritative when recorded. Legacy aliases bridge sparse category indexes.
    aliases = {}
    for row in [x[2] for x in indexes] + [x[3] for x in extracted]:
        code = str(row.get('paper_code') or row.get('paper_id') or '')
        doi = normalize_doi(row.get('doi'))
        if doi and code:
            if code in aliases and aliases[code] != doi:
                raise ValueError(f'Conflicting DOI for legacy paper code {code}')
            aliases[code] = doi
    papers, occurrences, evidence = {}, [], {}

    def register(row, location):
        code = str(row.get('paper_code') or row.get('paper_id') or '')
        doi = normalize_doi(row.get('doi')) or aliases.get(code, '')
        url = row.get('source_url') or row.get('input_value') or ''
        key = 'doi:' + doi if doi else ('legacy:' + code if code else 'title:' + str(row.get('source_title', '')).strip().casefold())
        pid = 'PAPER-' + _digest(key)
        p = papers.setdefault(pid, dict(paper_id=pid, identity_key=key, legacy_codes=set(), source_title='', doi=doi,
                                       source_url='', year=None, registry_sections=set(), diseases=set(), rois=set(), locations=set()))
        if code: p['legacy_codes'].add(code)
        for field in ('source_title', 'year'):
            if not p[field] and row.get(field): p[field] = row[field]
        if url and not p['source_url']: p['source_url'] = url
        p['locations'].add(location)
        if '/Disease/' in location: p['registry_sections'].add('Disease')
        if '/ROI/' in location: p['registry_sections'].add('ROI')
        p['diseases'].update(row.get('diseases', []))
        p['rois'].update(row.get('rois', []))
        if row.get('roi_name'): p['rois'].add(row['roi_name'])
        return pid

    for path, i, row in indexes:
        pid = register(row, path)
        occurrences.append(dict(paper_id=pid, registry_path=path, json_pointer=f'/{i}',
                                evidence_use=row.get('evidence_use', ''), kind='source_index_only',
                                embedded_quantitative_rows=len(row.get('quantitative_evidence', []))))
    for path, i, kind, row in extracted:
        pid = register(row, path)
        # Identity intentionally includes the complete source row: conflicting values remain visible.
        eid = 'EVID-' + _digest([pid, kind, row])
        loc = f'{path}#/{i}'
        if eid in evidence:
            evidence[eid]['registry_locations'] += ' | ' + loc
            continue
        evidence[eid] = dict(row, paper_id=pid, evidence_id=eid, evidence_kind=kind,
            registry_locations=loc,
            source_location=row.get('source_location') or row.get('table_or_figure') or row.get('source_file') or 'Not recorded',
            source_original=row.get('source_original') or 'Not recorded; existing summary is not a quotation',
            extraction_method=row.get('extraction_method') or 'Not recorded',
            extraction_status=row.get('extraction_status') or 'legacy_extraction_not_reaudited',
            historical_review_status=row.get('historical_review_status') or row.get('manual_review_status') or 'Not recorded',
            manual_review_status=row.get('human_review_status', 'pending_human_review'),
            source_check_status=row.get('source_check_status', 'not_checked_this_audit'),
            numeric_use=False)
    ev = pd.DataFrame(evidence.values())
    pp = []
    for pid, p in papers.items():
        for key, val in list(p.items()):
            if isinstance(val, set): p[key] = ' | '.join(sorted(val))
        subset = ev.loc[ev.paper_id.eq(pid)] if len(ev) else ev
        p['unique_evidence_rows'] = len(subset)
        p['group_distribution_rows'] = int(subset.evidence_kind.eq('group_distribution').sum()) if len(subset) else 0
        p['source_index_occurrences'] = sum(o['paper_id'] == pid for o in occurrences)
        p['human_accepted_rows'] = int(subset.manual_review_status.eq('accepted').sum()) if len(subset) else 0
        p['quantitative_records'] = int(subset.evidence_kind.isin(['group_distribution', 'supplement_distribution', 'reported_statistics']).sum()) if len(subset) else 0
        reported = subset.loc[subset.evidence_kind.eq('reported_statistics')] if len(subset) else subset
        p['reported_statistic_records'] = len(reported)
        p['reported_statistics_scope'] = ' | '.join(sorted(set(reported.applicability_note.dropna()))) if len(reported) else ''
        p['qualitative_records'] = int(subset.evidence_kind.eq('regional_result').sum()) if len(subset) else 0
        p['method_records'] = int(subset.evidence_kind.eq('method_evidence').sum()) if len(subset) else 0
        p['zero_evidence_reason'] = 'Source registered; no extracted records in connected evidence files' if not len(subset) else ''
        pp.append(p)
    paper_frame = pd.DataFrame(pp).sort_values(['legacy_codes', 'paper_id']).reset_index(drop=True)
    occurrence_frame = pd.DataFrame(occurrences)
    audit = dict(papers=paper_frame, evidence=ev, occurrences=occurrence_frame)
    if output_dir:
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        for name, frame in audit.items(): frame.to_csv(out / f'literature_audit_{name}.csv', index=False)
        (out / 'literature_audit.html').write_text(audit_html(audit), encoding='utf-8')
    return audit


def _table(frame):
    if frame.empty: return '<p>No records.</p>'
    from research_report_release import final_frame
    frame = final_frame(frame)
    from report_table_display import table_html
    return '<div style="overflow:auto;max-height:550px">' + table_html(frame) + '</div>'


def audit_html(audit, paper_id=None):
    papers = audit['papers']
    if paper_id: papers = papers.loc[papers.paper_id.eq(paper_id)]
    body = '<h3>Literature evidence</h3><p>Counts are unique extracted records, not category appearances or subject matches. Source indexes contribute zero extracted evidence. Source permission and measurement applicability are separate.</p>'
    for _, p in papers.iterrows():
        subset = audit['evidence'].loc[audit['evidence'].paper_id.eq(p.paper_id)]
        url = 'https://doi.org/' + p.doi if p.doi else p.source_url
        link = f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">Source paper</a>' if urlsplit(str(url)).scheme in ('http', 'https') else 'Source URL not recorded'
        body += f'<details id="{p.paper_id}" open><summary>{html.escape(p.legacy_codes)} — {html.escape(p.source_title)} — {p.unique_evidence_rows} evidence rows</summary>'
        body += f'<p>{link} | {p.paper_id} | Human accepted: {p.human_accepted_rows}</p>'
        if p.doi == '10.1159/000084560':
            from research_report_release import final_frame
            subset = final_frame(subset)
        summary_cols = [c for c in ['evidence_id', 'evidence_kind', 'roi_name', 'hemisphere', 'imaging_metric', 'diagnosis', 'reported_value', 'standard_deviation', 'interval_months', 'cohort_sample_size', 'unit', 'confidence_interval_lower', 'confidence_interval_upper', 'source_location', 'source_check_status', 'manual_review_status'] if c in subset]
        body += _table(subset[summary_cols])
        if p.doi == '10.1159/000084560':
            from barnes_fulltext_review import render
            body += render()
        if p.doi == '10.1016/j.neurobiolaging.2007.02.011':
            from dis009_fulltext_review import render
            body += render()
        if p.doi == '10.1159/000258100':
            from dis006_fulltext_review import render
            body += render()
        if p.doi == '10.1212/wnl.0b013e3181a4124e':
            from dis011_fulltext_review import render
            body += render()
        from hippocampal_fulltext_review import DOIS, render as render_hippocampal
        for code, doi in DOIS.items():
            if p.doi == doi:
                body += render_hippocampal(code=code)
        from covariate_fulltext_review import DOI as COVARIATE_DOI, render as render_covariate
        if p.doi == COVARIATE_DOI:
            body += render_covariate()
        for record in subset.to_dict('records'):
            body += '<details><summary>' + html.escape(record['evidence_id']) + ' — source and extraction details</summary>'
            from research_report_release import final_frame
            presented = final_frame(pd.DataFrame([record])).iloc[0].to_dict()
            fields = {k: v for k, v in presented.items() if not (v is None or (isinstance(v, float) and pd.isna(v)))}
            body += _table(pd.DataFrame(fields.items(), columns=['field', 'value'])) + '</details>'
        body += '<details><summary>Category occurrences (excluded from evidence count)</summary>'
        body += _table(audit['occurrences'].loc[audit['occurrences'].paper_id.eq(p.paper_id)]) + '</details></details>'
    return body


def evidence_is_rejected(row):
    fields = ('human_review_status', 'manual_review_status', 'source_review_status', 'case_review_status')
    return any(str(row.get(field, '')).strip().lower() == 'rejected' for field in fields)


def qualitative_candidates(audit):
    candidates = []
    for row in audit['evidence'].to_dict('records'):
        if evidence_is_rejected(row):
            continue
        if row.get('manual_review_status') != 'accepted':
            continue
        if row.get('evidence_kind') in ('method_evidence', 'supplement_distribution', 'reported_statistics') or not isinstance(row.get('roi_name'), str):
            continue
        candidates.append(row)
    return candidates
