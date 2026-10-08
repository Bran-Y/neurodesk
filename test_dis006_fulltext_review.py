import json
from pathlib import Path
import shutil
import tempfile
import unittest

import pandas as pd

from dis006_fulltext_review import DOI, SOURCE, MANIFEST, PDF, SCOPE, records, verify, render
from literature_audit import build_literature_audit, qualitative_candidates
from refresh_dis006_reports import verify_coverage

ROOT = Path(__file__).resolve().parent


class Dis006Tests(unittest.TestCase):
    def test_inventory_subgroups_and_cross_sectional_design(self):
        data = verify(ROOT)
        rows = records()
        self.assertEqual(len(rows),192)
        self.assertEqual(len({r['record_id'] for r in rows}),192)
        self.assertEqual(data['cohort']['final_AD'],38)
        self.assertEqual(sum(data['cohort'][g] for g in ('AD_APOE4_noncarrier','AD_APOE4_heterozygote','AD_APOE4_homozygote')),38)
        self.assertIn('same-day',data['scan_design'])
        self.assertNotIn('interval_months',rows[0])

    def test_table2_ci_is_not_sd_or_ad_absolute_mean(self):
        rows = records()[:168]
        self.assertEqual(sum(r['statistic_kind']=='control_mean' for r in rows),42)
        self.assertEqual(sum(r['statistic_kind']=='mean_group_difference' for r in rows),126)
        self.assertTrue(all(r['standard_deviation'] is None and r['confidence_level']==.95 for r in rows))
        row = next(r for r in rows if r['roi_name']=='Entorhinal cortex' and r['hemisphere']=='lh' and r['apoe4_dose']==2)
        self.assertEqual((row['reported_value'],row['confidence_interval_lower'],row['confidence_interval_upper']),(.91,.63,1.18))
        self.assertEqual(row['imaging_metric'],'control_minus_ad_cortical_thickness_difference')
        negative = next(r for r in rows if r['roi_name']=='Anterior cingulated gyrus' and r['hemisphere']=='rh' and r['apoe4_dose']==0)
        self.assertEqual(negative['reported_value'],-.02)
        self.assertTrue(any('-0.00' in r['reported_text'] for r in rows))

    def test_composite_parcels_not_repeated_as_single_roi(self):
        rows = [r for r in records()[:168] if r['roi_name']=='Inferior frontal']
        self.assertEqual(len(rows),8)
        self.assertEqual(rows[0]['composite_components'],['pars opercularis','pars orbitalis','pars triangularis'])
        self.assertIsNone(rows[0]['composite_weights'])

    def test_adjusted_volumes_units_sd_and_unstarred_isthmus(self):
        rows = records()[168:]
        self.assertEqual(len(rows),24)
        self.assertEqual([r['reported_value'] for r in rows[:4]],[1109,987,1006,1000])
        self.assertTrue(all(r['unit']=='ml' for r in rows[:8]))
        self.assertTrue(all(r['unit']=='mm3' for r in rows[8:]))
        self.assertTrue(all(r['standard_deviation'] is not None and r['confidence_interval_lower'] is None for r in rows))
        homo = [r for r in rows if r['roi_name']=='isthmus_cingulate' and r['apoe4_dose']==2]
        self.assertEqual([r['paper_significance_marker'] for r in homo],['',''])
        self.assertEqual([r['exact_p_from_results'] for r in homo],[.4,.05])
        self.assertTrue(all('No multiplicity' in r['corrected_significance_status'] for r in rows))

    def test_context_counts_never_authorize_patient_or_human_qc(self):
        audit = build_literature_audit(ROOT)
        paper = audit['papers'].set_index('doi').loc[DOI]
        self.assertEqual(paper.unique_evidence_rows,192)
        self.assertEqual(paper.reported_statistic_records,192)
        self.assertEqual(paper.group_distribution_rows,0)
        self.assertEqual(paper.human_accepted_rows,0)
        audit['evidence'].loc[audit['evidence'].doi.eq(DOI),'manual_review_status']='accepted'
        self.assertFalse(any(r['doi']==DOI for r in qualitative_candidates(audit)))
        self.assertTrue(all(r['numeric_use'] is False and r['comparison_compatible'] is False for r in records()))

    def test_missing_or_changed_primary_source_and_data_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (MANIFEST,SOURCE,PDF):
                target = root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
            verify(root)
            changed = records()
            changed[0]['standard_deviation']=.1
            (root/SOURCE).write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'table values'):
                verify(root)
            (root/PDF).unlink()
            with self.assertRaisesRegex(ValueError,'primary PDF'):
                verify(root)

    def test_final_disposition_and_figure_significance_are_separate(self):
        from research_report_release import final_frame, assert_final_text
        from zero_paper_review import review_for
        shown = final_frame(pd.DataFrame(records()))
        self.assertTrue(shown.evidence_disposition.str.contains('APOE-stratified').all())
        assert_final_text(render(ROOT))
        self.assertIn('Full-text',review_for(dict(doi=DOI,legacy_codes='DIS-006'))['source_review_scope'])
        self.assertIn('did not reach significance',verify(ROOT)['figure2'])

    def test_source_refresh_cannot_change_matches_or_other_papers(self):
        after = build_literature_audit(ROOT)['papers'].copy()
        after['zero_match_reason']=''
        after['paired_features_exploratory']=0
        hit=after.doi.eq(DOI)
        after.loc[hit,'zero_match_reason']=SCOPE
        before=after.copy()
        before.loc[hit,['unique_evidence_rows','quantitative_records','reported_statistic_records']]=0
        before.loc[hit,'locations']=before.loc[hit,'locations'].str.replace(' | '+SOURCE,'',regex=False)
        before.loc[hit,'reported_statistics_scope']=''
        before.loc[hit,'zero_match_reason']='Catalog entry only'
        before.loc[hit,'zero_evidence_reason']='Source registered; no extracted records in connected evidence files'
        verify_coverage(before,after)
        verify_coverage(after,after)
        verify_coverage(before.loc[~hit].reset_index(drop=True),after.loc[~hit].reset_index(drop=True))
        for column,value in [('human_accepted_rows',192),('paired_features_exploratory',1)]:
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
