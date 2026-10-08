"""Human-readable missing cells without changing source data or numeric formatting."""
import re


MISSING_CELL = re.compile(
    r'(<td\b[^>]*>)\s*(?:nan|none|nat|&lt;na&gt;|<na>)\s*(</td>)',
    re.IGNORECASE,
)


def clean_missing_cells(content):
    return MISSING_CELL.sub(r'\1Not available\2', content)


def table_html(frame, **options):
    options.setdefault('index', False)
    options['escape'] = True
    options['na_rep'] = 'Not available'
    return clean_missing_cells(frame.to_html(**options))
