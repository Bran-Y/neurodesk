import json
from pathlib import Path
import shutil
import tempfile
import unittest
import pandas as pd
from covariate_fulltext_review import DOI,SOURCE,MANIFEST,PDF,FIELD_CHECK,SCOPE,records,verify,render
from literature_audit import build_literature_audit,qualitative_candidates
from refresh_covariate_reports import verify_coverage
from research_report_release import assert_final_text,disposition
from zero_paper_review import review_for

ROOT=Path(__file__).parent


class CovariateReviewTests(unittest.TestCase):
    def test_inventory_and_units(self):
        rows=records()
        self.assertEqual(len(rows),56)
        self.assertEqual(len({r['record_id'] for r in rows}),56)
        tiv=[r for r in rows if r['covariate']=='log_tiv']
        self.assertEqual(len(tiv),16)
        self.assertTrue(all(r['unit']=='dimensionless log-log power coefficient' for r in tiv))
        hip=[r for r in rows if r['roi_name']=='hippocampus']
        self.assertTrue(all(r['hemisphere']=='bilateral_total' for r in hip))
        self.assertEqual([r['reported_value'] for r in hip],[-.32,1.78,.32,-.36,-3.32,.51,-1.17])

    def test_no_individual_prediction(self):
        for row in records():
            for key in ('numeric_use','patient_numeric_use','comparison_compatible','direction_eligible','model_reconstruction_complete'):
                self.assertIs(row[key],False)
            for key in ('mean','standard_deviation','intercept','residual_standard_deviation'):
                self.assertIsNone(row[key])
            self.assertEqual(row['human_review_status'],'not_assigned_by_assistant')
            self.assertNotIn('atrophy',row['imaging_metric'])

    def test_models_and_test_scope(self):
        for row in records():
            self.assertIn('upgrade',row['model_covariates'])
            if row['model_number']==4:
                self.assertEqual(row['model_covariates'],['age','gender','log_tiv','upgrade'])
            self.assertEqual(row['p_test'],'no association')
            self.assertIn('FDR not transferred',row['multiplicity_correction'])
        self.assertTrue(any(r['semipartial_r2_comparator']=='<' for r in records()))

    def test_conflicts_are_retained(self):
        data=verify(ROOT)
        self.assertEqual(data['statistics_count'],56)
        self.assertEqual(data['table_field_checks'],392)
        self.assertEqual(len(data['source_conflicts']),14)
        self.assertTrue(any('p=0.038' in finding['finding'] for finding in data['source_conflicts']))
        self.assertIn('Female n printed as 4',data['source_conflicts'][0]['finding'])
        self.assertIn('arithmetic inference',data['source_conflicts'][0]['finding'])
        wm=next(r for r in records() if r['roi_name']=='white matter' and r['covariate']=='log_tiv' and r['model_number']==4)
        self.assertEqual(wm['estimated_effect'],1.27)

    def test_catalog_and_no_classifier_leak(self):
        audit=build_literature_audit(ROOT)
        paper=audit['papers'].loc[audit['papers'].doi.eq(DOI)].iloc[0]
        self.assertEqual((paper.unique_evidence_rows,paper.quantitative_records,paper.reported_statistic_records,paper.human_accepted_rows),(56,56,56,0))
        audit['evidence'].loc[audit['evidence'].doi.eq(DOI),'manual_review_status']='accepted'
        self.assertFalse(any(r.get('doi')==DOI for r in qualitative_candidates(audit)))
        self.assertIn('Full-text',review_for(paper.to_dict())['source_review_scope'])
        self.assertIn('not a patient prediction model',disposition(records()[0]))

    def test_tampered_sources_fail_closed(self):
        for filename in (PDF,FIELD_CHECK,SOURCE,MANIFEST):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for name in (PDF,FIELD_CHECK,SOURCE,MANIFEST):
                    target=root/name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(ROOT/name,target)
                with (root/filename).open('ab') as stream:
                    stream.write(b'altered')
                with self.assertRaises((ValueError,json.JSONDecodeError)):
                    verify(root)

    def test_guarded_coverage_migration(self):
        after=build_literature_audit(ROOT)['papers']
        after['zero_match_reason']=''
        hit=after.doi.eq(DOI)
        after.loc[hit,'zero_match_reason']=SCOPE
        before=after.copy(deep=True)
        for key in ('unique_evidence_rows','quantitative_records','reported_statistic_records'):
            before.loc[hit,key]=0
        before.loc[hit,'rois']='intracranial volume | whole brain'
        before.loc[hit,'locations']=before.loc[hit,'locations'].iloc[0].replace(' | '+SOURCE,'')
        before.loc[hit,'reported_statistics_scope']=''
        before.loc[hit,'zero_match_reason']='Catalog entry only'
        before.loc[hit,'zero_evidence_reason']='Source registered; no extracted records in connected evidence files'
        verify_coverage(before,after)
        for column in ('human_accepted_rows','group_distribution_rows','method_records','quantitative_records'):
            changed=after.copy(deep=True)
            changed.loc[hit,column]+=1
            with self.assertRaises(AssertionError):
                verify_coverage(before,changed)
        changed=after.copy(deep=True)
        changed.loc[~hit,'unique_evidence_rows']+=1
        with self.assertRaises(AssertionError):
            verify_coverage(before,changed)

    def test_render_and_absent_source(self):
        page=render(ROOT)
        assert_final_text(page)
        self.assertIn('56 covariate effects',page)
        self.assertIn('not corrected',page)
        self.assertIn('1.27',page)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(verify(directory))
            self.assertEqual(render(directory),'')


if __name__=='__main__': unittest.main()
