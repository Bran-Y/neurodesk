"""Source-bound FTLD lobar statistics; never single-parcel disease references."""
import hashlib
import html
import json
from pathlib import Path

DOI = '10.1212/wnl.0b013e3181a4124e'
URL = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2827264/'
TITLE = 'Patterns of cortical thinning in the language variants of frontotemporal lobar degeneration'
FOLDER = 'workflow_sources/paper_reading_reviews/'
SOURCE = FOLDER + 'rohrer_2009_reported_statistics.json'
MANIFEST = FOLDER + 'rohrer_2009_fulltext_review.json'
RAW = {
    FOLDER+'raw/rohrer_2009_pmc_article.txt': 'd63dfe57eb7f32f4bb21874a00ae21ee77974b6457889a5634bb48a4a4ed71ec',
    FOLDER+'raw/rohrer_2009_table_browser.png': 'ac924b1d169a21eaee596dbbfa71d95d6a93fa371428ca7c2df2dfe059edafe9',
}
SCOPE = ('Verified FTLD language-subtype lobar thickness mean/SD in mm, not single DK parcel references. '
         'SemD/PNFA naming-severity groups are cross-sectional, not longitudinal stages or AD/PD labels. '
         'Modified FreeSurfer 4.0.3 and lobar aggregation are not calibrated to current patient processing. '
         'Context only; no patient numerical comparison or disease classification.')
# Values follow the six columns: frontal L/R, temporal L/R, parietal L/R.
TABLE = [
    ('SemD 1',9,'>9',12.0,2.0,'2.1/.2 2.2/.1 1.7/.2* 2.1/.2* 2.0/.1 2.0/.2'),
    ('SemD 2',11,'3-9',5.4,2.0,'2.0/.1 2.1/.2 1.6/.1* 2.0/.2* 1.8/.1 1.9/.2'),
    ('SemD 3',8,'<3',0.8,0.9,'1.8/.1* 2.1/.2 1.5/.1* 2.0/.1* 1.7/.1* 1.9/.2'),
    ('PNFA 1',11,'>24',26.8,1.0,'2.1/.2 2.1/.2 2.3/.3 2.3/.4 1.9/.2 1.9/.2'),
    ('PNFA 2',11,'14-24',19.7,4.1,'2.0/.1 2.2/.2 2.2/.3 2.4/.3 1.9/.1 2.0/.2'),
    ('PNFA 3',6,'<14',10.5,3.0,'2.0/.1* 2.1/.1 2.0/.3* 2.3/.4 1.8/.1* 1.9/.2'),
    ('Controls',29,None,None,None,'2.2/.2 2.2/.1 2.4/.3 2.3/.3 2.0/.2 2.0/.2'),
]


def records():
    rows = []
    columns = [(lobe,side) for lobe in ('frontal_lobe','temporal_lobe','parietal_lobe') for side in ('lh','rh')]
    for group,n,score_range,score_mean,score_sd,values in TABLE:
        for (roi,side),pair in zip(columns,values.split()):
            mean,sd = map(float,pair.rstrip('*').split('/'))
            rows.append(dict(record_id=f'DIS011-{group.replace(" ","-")}-{roi}-{side}',
                paper_code='DIS-011',doi=DOI,source_title=TITLE,source_url=URL,
                source_location='Table: Comparison of disease groups by naming score and cortical thickness in each lobe',
                source_check_status='primary_fulltext_statistics_verified_context_only',
                extraction_status='fulltext_lobar_table_verified',
                human_review_status='not_assigned_by_assistant',cohort_group=group,
                diagnosis='Control' if group=='Controls' else group.split()[0],
                cohort_sample_size=n,roi_name=roi,hemisphere=side,spatial_level='lobe',
                imaging_metric='lobar_mean_cortical_thickness',statistic_type='mean_and_standard_deviation',
                reported_value=mean,mean=mean,standard_deviation=sd,unit='mm',
                confidence_interval_lower=None,confidence_interval_upper=None,
                naming_score_range=score_range,naming_score_mean=score_mean,naming_score_sd=score_sd,
                significance_marker_as_reported='*' if pair.endswith('*') else None,
                p_as_reported='<0.05' if pair.endswith('*') else None,
                corrected_status='not_specified_for_lobar_table',
                raw_reported_text=f'{mean:.1f} ({sd:.1f})'+('*' if pair.endswith('*') else ''),
                processing_method='FreeSurfer 4.0.3 with local brain masks and ventricular white-mask modification',
                numeric_use=False,patient_numeric_use=False,comparison_compatible=False,
                applicability_note=SCOPE))
    return rows


def manifest():
    return dict(doi=DOI,review_type='assistant_primary_source_check_not_human_signoff',
        reviewed_sections=['Subjects','Image acquisition and analysis','Statistical analysis','Table','Results','Discussion'],
        primary_source_url=URL,source_sha256=RAW,statistics_count=42,
        original_cohort={'SemD':44,'PNFA':32,'Control':29},
        naming_analysis_cohort={'SemD':28,'PNFA':28,'Control':29},
        pathology_confirmed={'SemD':11,'PNFA':4},
        subgroup_definition='Naming performance within six months of MRI; cross-sectional stratification, not serial scanning.',
        table_marker='* p<0.05 disease group versus controls; table footnote does not specify correction.',
        vertex_model='Age, sex and scanner covariates; surface maps FDR 0.05, 20 mm smoothing.',
        roi_model='Between SemD and PNFA: thickness normalized by each patient average over their regions; FDR 0.05.',
        table_warning='Absolute lobar mean/SD cannot be assigned to normalized ROI contrasts or each DK parcel. No individual prediction interval or complete lobar aggregation rule provided.',
        method='Modified FreeSurfer 4.0.3, local semi-automated brain mask and ventricle-modified white mask; visual inspection and control-point editing as required.',
        main_patterns={'SemD':'Left-predominant anterior/inferior temporal thinning with less extensive right temporal involvement.',
                       'PNFA':'Predominantly left superior temporal, inferior/superior frontal and insular thinning; no significant right hemisphere thinning in whole-group versus controls.'},
        pathology_warning='PNFA pathology is heterogeneous; four tau-positive cases are not all 32 PNFA patients. Do not infer molecular pathology or AD/PD from MRI.',
        naming_warning='Equivalent naming-score conversion uses unpublished PhD data; do not reproduce a patient score conversion.',
        figure_scope='Figures 1-4 captions and Results checked; exact per-cluster p values, coordinates and extents not extracted from colored overlays.',
        permitted_use=SCOPE,human_signatures_changed=False,patient_qc_changed=False)


def verify(root=None):
    root = Path(root or Path(__file__).parent)
    if not (root/MANIFEST).exists():
        return None
    if json.loads((root/MANIFEST).read_text()) != manifest():
        raise ValueError('DIS-011 source manifest changed')
    for path,digest in RAW.items():
        if hashlib.sha256((root/path).read_bytes()).hexdigest()!=digest:
            raise ValueError('DIS-011 retained primary source changed: '+path)
    if json.loads((root/SOURCE).read_text())!=records():
        raise ValueError('DIS-011 source table extraction changed')
    return manifest()


def render(root=None):
    data = verify(root)
    if data is None:
        return ''
    escape = html.escape
    descriptions=[SCOPE,'SemD 44, PNFA 32, controls 29; naming-severity table uses 28 SemD and 28 PNFA.',
        data['subgroup_definition'],data['table_marker'],data['vertex_model'],data['roi_model'],
        data['table_warning'],data['method'],data['pathology_warning'],data['naming_warning'],data['figure_scope']]
    content='<details><summary>DIS-011: verified FTLD lobar table (42 estimates)</summary>'
    content+=''.join('<p>'+escape(s)+'</p>' for s in descriptions)
    content+='<p><a href="'+URL+'">Primary full text and table</a></p>'
    content+='<details><summary>Table: all reported lobar thickness statistics</summary><table><tr><th>Group / n</th><th>Lobe / side</th><th>Mean (SD), mm</th><th>Marker</th></tr>'
    for row in records():
        content+='<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [
            row['cohort_group']+' / '+str(row['cohort_sample_size']),row['roi_name']+' / '+row['hemisphere'],
            row['raw_reported_text'],row['p_as_reported'] or 'Not marked'])+'</tr>'
    return content+'</table></details></details>'
