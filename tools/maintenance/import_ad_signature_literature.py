"""Reproducible intake of reviewed AD literature; not a patient classifier."""
import json
from pathlib import Path
from workflow_paths import project_root

ROOT = project_root()
SOURCES = [
    dict(paper_code='AD-SIG-2009', year=2009, doi='10.1093/cercor/bhn113',
         source_title="The Cortical Signature of Alzheimer's Disease: Regionally Specific Cortical Thinning Relates to Symptom Severity in Very Mild to Mild AD Dementia and is Detectable in Asymptomatic Amyloid-Positive Individuals",
         source_url='https://surfer.nmr.mgh.harvard.edu/pub/articles/CerebralCortexMar09.pdf',
         methods='FreeSurfer, release not specified. Custom effect-defined ROIs; left/right ROI thickness averaged. Exploratory vertex threshold p<0.01 uncorrected; ROI analyses uncorrected. Not equivalent to standard gyral labels.',
         extraction_scope='Tables 2, 3 and 4; cortical thickness and group effects. Table values take precedence over prose. Not a complete extraction of demographics or all text results.'),
    dict(paper_code='AD-SIG-2011', year=2011, doi='10.1212/wnl.0b013e3182166e96',
         source_title='Alzheimer-signature MRI biomarker predicts AD dementia in cognitively normal adults',
         source_url='https://pmc.ncbi.nlm.nih.gov/articles/PMC3087406/',
         methods='Longitudinal initially cognitively normal cohorts: MGH 25 stable/8 converters; Rush 25 stable/7 converters. Predefined AD-signature cortical ROIs. Conversion status is a follow-up outcome, not baseline AD diagnosis.',
         extraction_scope='Table 2; four Cox hazard ratios and three pooled thickness-stratum conversion percentages on printed p1398. Supplementary methods and effect-size table not included.'),
    dict(paper_code='AD-WESTMAN-2011', year=2011, doi='10.1016/j.neuroimage.2011.06.065',
         source_title="AddNeuroMed and ADNI: Similar patterns of Alzheimer's atrophy and automated MRI classification accuracy in Europe and North America",
         source_url='https://doi.org/10.1016/j.neuroimage.2011.06.065',
         methods='FreeSurfer 4.5.0; 34 bilateral-averaged cortical thickness and 23 regional volume inputs. Volumes ICV normalized. OPLS classification; 7-fold cross-validation and cross-cohort tests. 1074 participants: AD 295, MCI 444, controls 335.',
         extraction_scope='Tables 3, 4 and 5: classification performance, model agreement, MCI follow-up. Printed confidence intervals retained, not recalculated. No deployable OPLS coefficients extracted.'),
]
ROWS = []


def add(source, location, **values):
    paper = SOURCES[source]
    row = {k: v for k, v in paper.items() if k not in ('methods', 'extraction_scope')}
    row.update(source_location=location, source_check_status='checked_against_local_fulltext',
               human_review_status='pending_human_review',
               approval_record='User authorized library inclusion on 2026-10-12; not blanket verification of every extracted value.',
               extraction_status='fulltext_selected_tables_extracted',
               extraction_method='Structured transcription checked against PDF tables; table-first policy.',
               comparison_compatible=False,
               applicability_note='Library evidence only. Custom ROI mapping or fitted model transfer has not been validated; not a patient threshold or disease probability.')
    row.update(values)
    ROWS.append(row)


ROIS = ['Medial temporal', 'Inferior temporal', 'Temporal pole', 'Angular',
        'Superior frontal', 'Superior parietal', 'Supramarginal', 'Precuneus',
        'Inferior frontal', 'Primary visual']
T2 = [
    [2.91,.33,2.51,.32,.40,13.62,1.22], [2.67,.23,2.36,.23,.31,11.46,1.33],
    [2.63,.21,2.39,.20,.25,9.31,1.20], [2.32,.16,2.10,.24,.22,9.60,1.09],
    [2.55,.17,2.35,.22,.20,7.83,1.02], [2.02,.13,1.87,.14,.15,7.51,1.12],
    [2.38,.17,2.18,.20,.20,8.43,1.08], [2.21,.18,2.03,.18,.18,8.07,.99],
    [2.16,.13,2.01,.15,.15,6.96,1.07], [1.51,.12,1.48,.14,.03,2.29,.27],
]
for roi, values in zip(ROIS, T2):
    for group, n, offset in [('OC',115,0), ('Mild AD',29,2)]:
        add(0, 'Table 2; printed p502; PDF p6', roi_name=roi, hemisphere='bilateral_mean',
            diagnosis=group, cohort='Sample 1a', cohort_sample_size=n,
            imaging_metric='cortical_thickness', reported_value=values[offset],
            standard_deviation=values[offset+1], unit='mm',
            control_minus_ad_mm=values[4], percent_thinning=values[5], cohens_d=values[6],
            significance='p<0.001, uncorrected' if roi!='Primary visual' else 'not significant')

T3 = [
    [.38,.36,.55,13,12.06,18.68,1.40,1.38,1.54,'***','***','***'],
    [.14,.25,.10,5.46,9.19,4.08,.50,1.48,.41,'','***',''],
    [.31,.22,.32,12.36,8.03,11.88,1.17,.93,1.55,'***','*','***'],
    [.09,.27,.21,4.20,11.91,9.25,.54,1.42,1.25,'','***','***'],
    [.11,.19,.32,4.75,8.03,12.96,.45,.98,1.45,'','**','***'],
    [.18,.08,.08,10.01,4.20,3.98,1.07,.41,.68,'**','','*'],
    [.20,.23,.16,9.18,10.04,6.80,1.09,1.05,.84,'**','**','*'],
    [.10,.18,.16,5.08,8.40,7.21,.51,.97,.74,'','*','*'],
    [.14,.13,.15,6.75,5.98,7.10,.85,.91,1.16,'*','*','***'],
    [.06,.00,.03,4.62,.16,2.28,.61,.02,.25,'','',''],
]
for roi, values in zip(ROIS,T3):
    for j in range(3):
        add(0, 'Table 3; printed p502; PDF p6', roi_name=roi, hemisphere='bilateral_mean',
            cohort=f'Sample {j+2}', imaging_metric='control_minus_ad_thickness',
            reported_value=values[j], unit='mm', percent_thinning=values[j+3],
            cohens_d=values[j+6], significance_marker=values[j+9],
            significance_key='* p<0.05; ** p<0.005; *** p<0.001; uncorrected; blank=no marked significance')

T4 = [
    [2.80,.30,2.63,.37,3.89,9.65,.36,.80,'V,A','C,I'],
    [2.62,.23,2.53,.20,1.69,4.97,.19,.60,'A','C,A'],
    [2.55,.24,2.52,.21,3.14,4.39,.37,.55,'A','C,A'],
    [2.21,.18,2.16,.14,4.46,6.39,.61,1.06,'C,A','C'],
    [2.49,.20,2.43,.19,2.29,4.84,.31,.67,'A','C'],
    [1.98,.18,1.92,.13,2.08,5.12,.27,.80,'A','C'],
    [2.28,.18,2.26,.18,3.88,4.89,.53,.67,'C,A','C'],
    [2.15,.28,2.08,.22,2.43,5.84,.23,.64,'A','C'],
    [2.14,.14,2.03,.19,1.15,6.28,.19,.85,'V,A','C,I'],
    [1.52,.16,1.50,.12,-.39,.89,-.04,.11,'',''],
]
for roi, values in zip(ROIS,T4):
    for j,(group,n) in enumerate([('Incipient AD',29),('Very mild AD',40)]):
        add(0,'Table 4; printed p503; PDF p7', roi_name=roi, hemisphere='bilateral_mean',
            cohort='Sample 1b', diagnosis=group, cohort_sample_size=n, unit='mm',
            imaging_metric='cortical_thickness', reported_value=values[2*j],
            standard_deviation=values[2*j+1], percent_thinning=values[4+j],
            cohens_d=values[6+j], significance_marker=values[8+j],
            significance_key='p<0.05 uncorrected vs C=OC,I=incipient,V=very mild,A=mild; OC values reused from Table 2, not independent evidence')

T2011 = [
    ('MTL',[3.28,.38,2.94,.43,3.37,.23,2.83,.39],'a','b'),
    ('Temporal pole',[3.07,.20,2.77,.30,3.02,.29,2.73,.31],'c','a'),
    ('Inferior temporal',[2.48,.20,2.39,.30,2.89,.26,2.70,.28],'',''),
    ('Angular gyrus',[2.48,.22,2.30,.25,2.50,.28,2.41,.23],'a',''),
    ('Supramarginal gyrus',[2.54,.17,2.38,.20,2.54,.26,2.38,.13],'a',''),
    ('Superior parietal',[2.17,.21,2.04,.19,2.05,.21,2.09,.25],'',''),
    ('Precuneus',[2.41,.17,2.25,.13,2.46,.22,2.38,.22],'',''),
    ('Middle frontal',[2.40,.16,2.24,.11,2.30,.15,2.20,.18],'a',''),
    ('Superior frontal',[2.58,.23,2.29,.19,2.68,.34,2.40,.19],'c','a'),
    ('Primary visual',[1.59,.12,1.55,.08,1.56,.17,1.68,.25],'',''),
    ('AD-signature summary measure',[2.49,.14,2.35,.17,2.65,.19,2.46,.12],'a','a'),
]
for roi,values,mgh,rush in T2011:
    for j,(cohort,group,n) in enumerate([('MGH','CN-stable',25),('MGH','CN-AD converter',8),('Rush','CN-stable',25),('Rush','CN-AD converter',7)]):
        add(1,'Table 2; printed p1398; PDF p4',roi_name=roi,cohort=cohort,
            diagnosis='Cognitively normal at baseline',followup_group=group,
            cohort_sample_size=n,imaging_metric='cortical_thickness',unit='mm',
            reported_value=values[2*j],standard_deviation=values[2*j+1],
            significance_marker=(mgh if j==1 else rush if j==3 else ''),
            significance_key='a p<0.05; b p<0.001; c p<0.005')
for metric,model,hr,lo,hi,p in [
    ('AD-signature thickness','univariate',3.5,2.0,6.4,.00005),
    ('AD-signature thickness','gender adjusted',3.4,1.7,6.9,.0005),
    ('Episodic memory Z score','univariate',3.1,1.6,6.1,.001),
    ('Episodic memory Z score','multivariate',3.2,1.5,6.6,.001)]:
    add(1,'Results; printed p1398; PDF p4',imaging_metric=metric,model=model,
        reported_value=hr,unit='hazard ratio per 1 SD decrease',confidence_interval_lower=lo,
        confidence_interval_upper=hi,confidence_level=.95,p_value_less_than=p,
        applicability_note='Longitudinal cohort hazard ratio, not a cross-sectional patient disease probability.')
for group,n,pct in [('low thickness',11,55),('average thickness',45,20),('high thickness',9,0)]:
    add(1,'Results; printed p1398; PDF p4',cohort=group,cohort_sample_size=n,
        imaging_metric='observed_followup_conversion',reported_value=pct,unit='percent',
        applicability_note='Cohort-derived +/-1 SD strata; observed follow-up proportion, not calibrated individual risk.')

PERFORMANCE = [
    ('AddNeuroMed CV', [79,70.8,85.4,90,83,94.3,84.3,79,88.4,7.9,4.5,13.9,.23,.16,.33]),
    ('ADNI CV',[86.9,81.1,91.1,86.7,81.6,90.5,86.8,83,94.3,6.5,4.7,9.1,.15,.10,.22]),
    ('Combined CV',[83.4,78.7,87.2,87.8,86.3,96.3,85.7,82.8,88.2,6.8,5.1,9.1,.19,.15,.25]),
    ('ADNI train; AddNeuroMed test',[75,66.3,81.7,92.7,84.1,95,83.4,78,87.7,10.3,5.2,20.2,.27,.20,.37]),
    ('AddNeuroMed train; ADNI test',[83,76.7,87.8,88.4,83.6,92,86,82.3,89.1,7.2,5,10.4,.19,.14,.27]),
]
for model,values in PERFORMANCE:
    for j,metric in enumerate(['sensitivity','specificity','accuracy','positive likelihood ratio','negative likelihood ratio']):
        add(2,'Table 3; printed p824; PDF p7',model=model,imaging_metric=metric,
            reported_value=values[3*j],confidence_interval_lower=values[3*j+1],
            confidence_interval_upper=values[3*j+2],unit='percent' if j<3 else 'ratio',
            applicability_note='Published model performance; printed intervals preserved. Not patient evidence or transferable model coefficients.')
for model,n,same,different,pct in [
    ('ANM vs combined',229,217,12,95),('ADNI vs combined',401,385,16,96),
    ('ANM vs ANM tested on ADNI-trained model',229,209,20,91),
    ('ADNI vs ADNI tested on ANM-trained model',401,372,29,93)]:
    add(2,'Table 4; printed p824; PDF p7',model=model,cohort_sample_size=n,
        imaging_metric='model_classification_agreement',reported_value=pct,unit='percent',
        same_classification=same,different_classification=different)
for group,n,ad,ctl,pct in [
    ('Combined converters',84,60,24,71),('Combined stable',353,141,212,40),
    ('AddNeuroMed converters',22,14,8,64),('AddNeuroMed stable',97,28,69,29),
    ('ADNI converters',62,46,16,74),('ADNI stable',256,113,143,44),('ADNI MCI to CTL',7,1,6,14)]:
    add(2,'Table 5; printed p824; PDF p7',cohort=group,cohort_sample_size=n,
        imaging_metric='baseline_AD_like_classification',reported_value=pct,unit='percent',
        ad_like_count=ad,control_like_count=ctl,interval_months=12,
        applicability_note='Published OPLS baseline classification by subsequent MCI outcome; pooled and component cohorts overlap.')


def main():
    base=ROOT/'workflow_sources'
    for source in SOURCES:
        source.update(evidence_category='disease_evidence',diseases=['AD'],
                      evidence_use='Extracted numeric literature context; patient transfer not established')
    for path,data in [(base/'Disease/ad_signature_sources.json',SOURCES),
                      (base/'paper_reading_reviews/ad_signature_reported_statistics.json',ROWS)]:
        path.write_text(json.dumps(data,indent=2,ensure_ascii=True)+'\n')
    print(f'Integrated {len(SOURCES)} sources and {len(ROWS)} numeric evidence records')


if __name__=='__main__':
    main()
