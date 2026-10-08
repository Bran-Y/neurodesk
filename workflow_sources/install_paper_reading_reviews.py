"""Idempotently link new source reviews without replacing existing registries."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    reviews = json.loads((ROOT/'paper_reading_reviews/three_paper_review.json').read_text())
    by_doi = {r['doi']: r for r in reviews}
    for folder in ('Disease', 'ROI'):
        root_file = ROOT/folder/('disease_literature_sources.json' if folder == 'Disease' else 'roi_literature_sources.json')
        records = json.loads(root_file.read_text())
        for review in reviews:
            existing = next((r for r in records if r.get('doi') == review['doi']), None)
            if existing is None:
                existing = dict(paper_code=review['paper_code'], source_title=review['source_title'],
                                doi=review['doi'], year=review['year'], input_value=review['source_url'],
                                diseases=review['diseases'], rois=review['rois'],
                                evidence_category='disease_evidence' if folder == 'Disease' else 'roi_evidence',
                                note='Source review only; numerical comparison not approved.')
                records.append(existing)
            existing['full_text_review_file'] = 'workflow_sources/paper_reading_reviews/three_paper_review.json'
            existing['full_text_review_key'] = review['doi']
        save(root_file, records)
        for path in (ROOT/folder).glob('*/*.json'):
            rows = json.loads(path.read_text())
            if not isinstance(rows, list):
                continue
            changed = False
            for row in rows:
                if isinstance(row, dict) and row.get('doi') in by_doi:
                    row['full_text_review_file'] = 'workflow_sources/paper_reading_reviews/three_paper_review.json'
                    row['full_text_review_key'] = row['doi']
                    changed = True
            if changed:
                save(path, rows)
        # Separate browse indexes; deduplicate by the canonical paper_code.
        categories = {}
        for review in reviews:
            record = next(r for r in records if r.get('doi') == review['doi'])
            for category in review['diseases'] if folder == 'Disease' else review['rois']:
                categories.setdefault(category.replace(' ', '_'), []).append(record)
        for category, rows in categories.items():
            save(ROOT/folder/category/'paper_reading_index.json', rows)
    print('Linked 3 source reviews to canonical registries and category indexes; no review approvals changed.')


if __name__ == '__main__':
    main()
