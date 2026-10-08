import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zero_paper_review import REVIEWS, catalog, new_statistics, notebook_review_url, publish, review_for

ROOT = Path(__file__).resolve().parent


class ZeroPaperReviewTests(unittest.TestCase):
    def test_inventory_every_source_once(self):
        papers, stats = catalog(ROOT)
        self.assertEqual(len(papers), 34)
        self.assertEqual({p['review_key'] for p in papers}, set(REVIEWS))
        self.assertEqual(len(stats), 30)

    def test_no_new_diagnosis_links_or_approval(self):
        for row in new_statistics():
            self.assertIs(row['comparison_compatible'], False)
            self.assertIs(row['patient_numeric_use'], False)
            self.assertNotEqual(row['human_review_status'], 'accepted')
            self.assertTrue(row['source_url'].startswith('https://'))

    def test_intervals_outlier_n_and_sign(self):
        rows = new_statistics()
        gray = [r for r in rows if r['review_key'] == 'DIS-007']
        self.assertEqual(len(gray), 20)
        self.assertEqual({r['interval_months'] for r in gray}, {6,12})
        negative = next(r for r in gray if r['mean'] == -0.01)
        self.assertEqual(negative['sample_size'], 18)
        self.assertEqual(negative['standard_deviation'], 1.97)
        self.assertEqual(negative['unit'], 'percent/year')

    def test_mean_only_not_fabricated_sd(self):
        from hippocampal_fulltext_review import records
        rows = [r for r in records() if r['paper_code'] == 'ROI-010']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['standard_deviation'] is None for r in rows))

    def test_method_difference_not_atrophy_rate(self):
        rows = [r for r in new_statistics() if r['review_key'] == 'ROI-007']
        self.assertEqual({r['imaging_metric'] for r in rows},
                         {'voxel_similarity','atrophy_rate_difference_from_manual'})
        self.assertTrue(all(r['interval_months'] is None for r in rows))

    def test_datasets_do_not_share_blank_doi_identity(self):
        papers, _ = catalog(ROOT)
        baseline = [dict(p, doi=p.get('doi') or 0, matched_group_effect_features=i)
                    for i,p in enumerate(papers)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'baseline.json'
            path.write_text(json.dumps(baseline))
            merged, _ = catalog(ROOT, path)
        actual = {p['review_key']:p['patient_match_total'] for p in merged}
        self.assertNotEqual(actual['DIS-003'], actual['ROI-001'])

    def test_partial_scope_and_independent_pd_counts(self):
        paper = dict(legacy_codes='ROI-006', doi='10.1097/rct.0b013e31802f4139')
        self.assertIn('Full-text', review_for(paper)['source_review_scope'])
        papers, _ = catalog(ROOT)
        pd_paper = next(p for p in papers if p['doi'] == '10.1371/journal.pone.0295069')
        self.assertEqual(pd_paper['unique_evidence_rows'], 0)
        self.assertEqual(pd_paper['additional_quantitative_records'], 85)

    def test_unknown_paper_not_silently_approved(self):
        with self.assertRaises(ValueError):
            review_for(dict(doi='10.1234/not-reviewed'))

    def test_notebook_link_uses_file_server_not_lab_route(self):
        with patch.dict('os.environ', {'JUPYTERHUB_SERVICE_PREFIX':'/user/reviewer/'}):
            url = notebook_review_url(Path.home() / 'neurodesk/project')
        self.assertEqual(url, '/user/reviewer/files/neurodesk/project/outputs/literature_zero_review_20261004/ZERO_PAPER_REVIEW.html')

    def test_review_text_is_english_including_fulltext_overrides(self):
        for key, value in REVIEWS.items():
            self.assertFalse(re.search(r'[\u3400-\u9fff]', ' '.join(value)), key)
            review = review_for(dict(legacy_codes=key, doi=key))
            self.assertFalse(re.search(r'[\u3400-\u9fff]', json.dumps(review, ensure_ascii=False)), key)
            self.assertEqual(review['review_type'], 'assistant_source_check_not_human_signoff')

    def test_published_page_and_exports_are_english(self):
        papers, stats = catalog(ROOT)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'workflow_sources').symlink_to(ROOT / 'workflow_sources', target_is_directory=True)
            with patch('zero_paper_review.catalog', return_value=(papers, stats)), \
                    patch('zero_paper_review.patient_match_inventory', return_value=[]):
                page = publish(root)
            content = page.read_text()
            self.assertIn('<html lang="en">', content)
            self.assertIn('Zero-count literature review', content)
            self.assertEqual(content.count('<article>'), 34)
            self.assertFalse(re.search(r'[\u3400-\u9fff]', content))
            for filename in ('paper_reviews.json', 'paper_reviews.csv'):
                self.assertFalse(re.search(r'[\u3400-\u9fff]', (page.parent / filename).read_text()))
            self.assertEqual(json.loads((page.parent / 'new_reported_statistics.json').read_text()), stats)


if __name__ == '__main__':
    unittest.main()
