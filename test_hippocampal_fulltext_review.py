import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from hippocampal_fulltext_review import DOIS, SOURCE, MANIFEST, RAW, SCOPES, records, verify, render
from literature_audit import build_literature_audit, qualitative_candidates
from refresh_hippocampal_reports import verify_coverage

ROOT=Path(__file__).parent


class HippocampalFulltextTests(unittest.TestCase):
    def test_source_bound_inventory(self):
        self.assertEqual(verify(ROOT)['statistics_count'],9)
        rows=records()
        self.assertEqual(len({r['record_id'] for r in rows}),9)
        self.assertEqual([r['mean'] for r in rows[:6]],[1.31,5.09,.89,5.34,.56,3.55])
        self.assertEqual([r['standard_deviation'] for r in rows[:6]],[2.,3.59,.75,3.43,1.12,2.70])

    def test_average_rate_not_total_volume_or_single_side(self):
        rows=records()[:6]
        self.assertEqual({r['hemisphere'] for r in rows},{'bilateral_average_rate'})
        self.assertTrue(all(r['interval_months'] is None for r in rows))
        self.assertTrue(all(r['statistic_type']=='back_transformed_mean_and_transformed_sd' for r in rows))

    def test_ci_is_not_sd_or_individual_interval(self):
        rows=records()[6:]
        self.assertEqual([(r['confidence_interval_lower'],r['confidence_interval_upper']) for r in rows],
                         [(-.30,1.62),(2.33,3.91),(4.15,7.03)])
        for row in rows:
            self.assertIsNone(row['standard_deviation'])
            self.assertEqual(row['hemisphere'],'not_specified_for_quoted_group_summary')
            self.assertNotIn('lower_95pi',row)

    def test_connected_without_duplicate_abstract_rows_or_approval(self):
        from zero_paper_review import new_statistics, review_for
        audit=build_literature_audit(ROOT)
        self.assertFalse(any(r['review_key'] in DOIS for r in new_statistics()))
        for code,doi in DOIS.items():
            row=audit['papers'].set_index('doi').loc[doi]
            self.assertEqual(row.reported_statistic_records,6 if code=='ROI-006' else 3)
            self.assertEqual(row.human_accepted_rows,0 if code=='ROI-006' else 1)
            self.assertIn('Full-text',review_for(dict(legacy_codes=code,doi=doi))['source_review_scope'])

    def test_never_becomes_patient_link(self):
        audit=build_literature_audit(ROOT)
        audit['evidence'].loc[audit['evidence'].doi.isin(DOIS.values()),'manual_review_status']='accepted'
        self.assertFalse(any(r.get('doi') in DOIS.values() for r in qualitative_candidates(audit)))
        for row in records():
            self.assertIs(row['patient_numeric_use'],False)
            self.assertIs(row['comparison_compatible'],False)
            self.assertIs(row['numeric_use'],False)

    def test_changed_primary_source_or_values_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in [SOURCE,MANIFEST,*RAW]:
                (root/name).parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,root/name)
            self.assertIsNotNone(verify(root))
            rows=records(); rows[-1]['standard_deviation']=1.44
            (root/SOURCE).write_text(json.dumps(rows))
            with self.assertRaises(ValueError): verify(root)
            (root/SOURCE).write_text(json.dumps(records()))
            (root/next(iter(RAW))).write_bytes(b'changed')
            with self.assertRaises(ValueError): verify(root)

    def test_migration_protects_other_sources_and_human_signatures(self):
        after=build_literature_audit(ROOT)['papers'].copy()
        after['zero_match_reason']=''
        before=after.copy()
        for code,doi in DOIS.items():
            hit=after.doi.eq(doi)
            after.loc[hit,'zero_match_reason']=SCOPES[code]
            before.loc[hit,['unique_evidence_rows','quantitative_records','reported_statistic_records']]=[0 if code=='ROI-006' else 1,0,0]
            before.loc[hit,'reported_statistics_scope']=''
            before.loc[hit,'locations']=before.loc[hit,'locations'].str.replace(' | '+SOURCE,'',regex=False)
            if code=='ROI-006': before.loc[hit,'zero_evidence_reason']='Source registered; no extracted records in connected evidence files'
        verify_coverage(before,after)
        for field in ['human_accepted_rows','unique_evidence_rows']:
            changed=after.copy(); changed.loc[changed.doi.eq(DOIS['ROI-006']),field]+=1
            with self.assertRaises(AssertionError): verify_coverage(before,changed)
        changed=after.copy(); changed.loc[~changed.doi.isin(DOIS.values()),'unique_evidence_rows']+=1
        with self.assertRaises(AssertionError): verify_coverage(before,changed)

    def test_render_and_legacy_fallback(self):
        self.assertIn('-0.30 to 1.62',render(ROOT,'ROI-010'))
        self.assertNotIn('ROI-006:',render(ROOT,'ROI-010'))
        from zero_paper_review import new_statistics
        with patch('hippocampal_fulltext_review.verify',return_value=None):
            self.assertEqual(len(new_statistics()),39)


if __name__=='__main__': unittest.main()
