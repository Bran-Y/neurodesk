"""Context-only statistics re-extracted from zero-main-catalog sources.

These records describe longitudinal atrophy or method agreement. They are
connected to the literature audit, never to single-scan patient inference.
"""

SOURCES = {
    'DIS-007': ('Gray matter atrophy rate as a marker of disease progression in AD', 2011,
                '10.1016/j.neurobiolaging.2010.11.001', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3657171/'),
    'ROI-005': ('Automatic calculation of hippocampal atrophy rates using a hippocampal template and the boundary shift integral', 2007,
                '10.1016/j.neurobiolaging.2006.07.008', 'https://pubmed.ncbi.nlm.nih.gov/16934913/'),
    'ROI-007': ('A comparison of methods for the automated calculation of volumes and atrophy rates in the hippocampus', 2008,
                '10.1016/j.neuroimage.2008.01.012', 'https://pubmed.ncbi.nlm.nih.gov/18353687/'),
}


def new_statistics():
    """Return the 30 source-reported values without inventing missing fields."""
    rows = []

    def add(code, group, metric, method, mean, sd, unit, n, location, interval=None, side=None):
        title, year, doi, url = SOURCES[code]
        rows.append(dict(record_id=f'{code}-{len(rows)+1:02d}', review_key=code,
            paper_code=code, source_title=title, year=year, doi=doi, source_url=url,
            diagnosis=group, imaging_metric=metric, measurement_method=method,
            mean=mean, reported_value=mean, standard_deviation=sd, unit=unit,
            sample_size=n, cohort_sample_size=n, source_location=location,
            interval_months=interval, hemisphere=side,
            source_check_status=('primary_fulltext_table_checked' if code == 'DIS-007'
                                 else 'primary_abstract_checked'),
            extraction_method=('Full-text Table 1 transcription' if code == 'DIS-007'
                               else 'PubMed abstract transcription'),
            extraction_status='source_checked_pending_human_review',
            human_review_status='not_assigned_by_assistant',
            comparison_compatible=False, numeric_use=False, patient_numeric_use=False,
            confidence_interval_lower=None, confidence_interval_upper=None,
            applicability_note=('Longitudinal/method statistic; not a single-scan regional reference interval. '
                                'Requires matched serial MRI measurement and independent method validation.')))

    for interval, values in [(6, [(0.86,4.24,2.20,2.66),(-0.01,1.97,2.31,2.60),
                                  (0.42,0.47,1.77,1.37),(0.51,0.57,1.67,1.26),(0.34,0.89,2.03,1.63)]),
                              (12, [(0.92,2.21,2.37,2.86),(0.49,1.19,2.76,1.64),
                                   (0.46,0.27,2.01,0.96),(0.64,0.44,1.99,0.91),(0.67,0.82,2.72,1.25)])]:
        methods = ['SPM5 segmentation/subtraction all subjects', 'SPM5 segmentation/subtraction excluding outliers',
                   'Jacobian integration', 'BBSI', 'SIENA']
        for i, (method, pair) in enumerate(zip(methods, values)):
            metric = 'global_gray_matter_annual_atrophy' if i < 3 else 'whole_brain_annual_atrophy'
            for group, mean, sd, n in [('Control',pair[0],pair[1],18 if i == 1 else 19),
                                       ('AD',pair[2],pair[3],36 if i == 1 else 37)]:
                add('DIS-007',group,metric,method,mean,sd,'percent/year',n,'Table 1',interval)
    for method, control, ad in [('manual',(18.1,53.5),(174.6,106.5)),
                                ('semi-automated HBSI',(15.3,50.2),(159.4,101.2)),
                                ('automated HBSI',(11.3,50.4),(172.1,123.1))]:
        for group, pair, n in [('Control',control,19),('AD',ad,36)]:
            add('ROI-005',group,'hippocampal_annual_volume_loss',method,*pair,'mm3/year',n,
                'PubMed abstract; publisher Results identifies total left + right',side='bilateral_total')
    for group, n, sim, diff in [('Control',19,(0.69,0.05),(0.03,1.29)),('AD',36,(0.72,0.06),(0.48,2.44))]:
        add('ROI-007',group,'voxel_similarity','automated vs manual',*sim,'unitless',n,'PubMed abstract')
        add('ROI-007',group,'atrophy_rate_difference_from_manual','BSI vs manual',*diff,'percent',n,
            'PubMed abstract; method error, not a group atrophy rate')
    return rows
