import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import pandas as pd
from dis011_fulltext_review import DOI,SOURCE,MANIFEST,RAW,SCOPE,records,manifest,verify,render
from refresh_dis011_reports import verify_coverage
from literature_audit import build_literature_audit,qualitative_candidates
from research_report_release import disposition
from zero_paper_review import review_for

ROOT=Path(__file__).parent


class FulltextReviewTests(unittest.TestCase):
    def test_table_inventory_and_groups(self):
        rows=records()
        self.assertEqual(len(rows),42)
        self.assertEqual(len({r['record_id'] for r in rows}),42)
        self.assertEqual({r['cohort_group']:r['cohort_sample_size'] for r in rows},
                         {'SemD 1':9,'SemD 2':11,'SemD 3':8,'PNFA 1':11,'PNFA 2':11,'PNFA 3':6,'Controls':29})
        self.assertEqual(manifest()['original_cohort'],{'SemD':44,'PNFA':32,'Control':29})

    def test_means_sd_stars_and_units(self):
        rows=records()
        self.assertEqual(sum(r['significance_marker_as_reported']=='*' for r in rows),11)
        self.assertEqual(rows[2]['raw_reported_text'],'1.7 (0.2)*')
        self.assertEqual(rows[-1]['raw_reported_text'],'2.0 (0.2)')
        self.assertTrue(all(r['unit']=='mm' and r['standard_deviation']>0 and
            r['confidence_interval_lower'] is None and r['corrected_status']=='not_specified_for_lobar_table' for r in rows))

    def test_no_patient_or_parcel_links_even_if_permission_added(self):
        rows=copy.deepcopy(records())
        self.assertTrue(all(r['numeric_use'] is False and r['comparison_compatible'] is False and
                            r['spatial_level']=='lobe' for r in rows))
        for r in rows:
            r['manual_review_status']='accepted'
            r['evidence_kind']='reported_statistics'
        self.assertEqual(qualitative_candidates({'evidence':pd.DataFrame(rows)}),[])

    def test_source_binding_and_tampering(self):
        self.assertEqual(verify(ROOT),manifest())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertIsNone(verify(root))
            for name in [SOURCE,MANIFEST,*RAW]:
                target=root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
            self.assertEqual(verify(root),manifest())
            data=json.loads((root/SOURCE).read_text())
            data[0]['mean']=9
            (root/SOURCE).write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                verify(root)
            shutil.copy2(ROOT/SOURCE,root/SOURCE)
            (root/next(iter(RAW))).write_text('tampered')
            with self.assertRaises(ValueError):
                verify(root)

    def test_connected_counts_and_disposition(self):
        audit=build_literature_audit(ROOT)
        row=audit['papers'].loc[audit['papers'].doi.eq(DOI)].iloc[0]
        self.assertEqual(row.unique_evidence_rows,43)
        self.assertEqual(row.reported_statistic_records,42)
        self.assertEqual(row.quantitative_records,42)
        self.assertEqual(row.human_accepted_rows,1)
        self.assertIn('not a single-parcel',disposition(records()[0]))
        self.assertIn('Full-text',review_for(row.to_dict())['source_review_scope'])
        self.assertIn('not longitudinal',render(ROOT))

    def test_refresh_changes_only_declared_source_cells(self):
        after=build_literature_audit(ROOT)['papers'].copy()
        after['zero_match_reason']=''
        hit=after.doi.eq(DOI)
        after.loc[hit,'zero_match_reason']=SCOPE
        before=after.copy()
        before.loc[hit,['unique_evidence_rows','quantitative_records','reported_statistic_records']]=[1,0,0]
        before.loc[hit,'reported_statistics_scope']=''
        before.loc[hit,'locations']=before.loc[hit,'locations'].str.replace(' | '+SOURCE,'',regex=False)
        before.loc[hit,'rois']=' | '.join(sorted(set(before.loc[hit,'rois'].iloc[0].split(' | '))-
                                            {r['roi_name'] for r in records()}))
        verify_coverage(before,after)
        verify_coverage(after,after)
        for column,value in [('human_accepted_rows',43),('quantitative_records',43)]:
            changed=after.copy()
            changed.loc[hit,column]=value
            with self.assertRaises(AssertionError):
                verify_coverage(before,changed)
        changed=after.copy()
        changed.loc[~hit,'unique_evidence_rows']+=1
        with self.assertRaises(AssertionError):
            verify_coverage(before,changed)


if __name__=='__main__':
    unittest.main()
