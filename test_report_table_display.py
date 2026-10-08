import unittest
from importlib.util import find_spec

import pandas as pd

from report_table_display import MISSING_CELL, clean_missing_cells, table_html


class TableDisplayTests(unittest.TestCase):
    def test_missing_types_readable_source_unchanged(self):
        source = pd.DataFrame({'value': [None, float('nan'), pd.NA, pd.NaT, 0, False]})
        before = source.copy(deep=True)
        shown = table_html(source)
        pd.testing.assert_frame_equal(source, before)
        self.assertEqual(shown.count('<td>Not available</td>'), 4)
        self.assertIn('<td>0</td>', shown)
        self.assertIn('<td>False</td>', shown)
        self.assertIsNone(MISSING_CELL.search(shown))

    def test_only_whole_missing_cells_changed(self):
        source = ('<p>NaN is a missing value.</p><th>None</th>'
                  '<td class="value"> NaN </td><td>None</td><td>&lt;NA&gt;</td>'
                  '<td>NaT</td><td>0.0</td><td>-0.357</td><td>nanotechnology</td>'
                  '<td>Missing reference</td><td></td><td>N/A</td>')
        shown = clean_missing_cells(source)
        self.assertEqual(shown.count('Not available'), 4)
        for text in ('<p>NaN is a missing value.</p>', '<th>None</th>', '<td>0.0</td>',
                     '<td>-0.357</td>', '<td>nanotechnology</td>',
                     '<td>Missing reference</td>', '<td></td>', '<td>N/A</td>'):
            self.assertIn(text, shown)
        self.assertEqual(clean_missing_cells(shown), shown)

    def test_numeric_format_and_escaping_preserved(self):
        source = pd.DataFrame({'value': [1.23456789, -0.357, float('nan')],
                               'note': ['<script>x</script>', '0', 'NaN']})
        self.assertEqual(table_html(source, border=0),
                         clean_missing_cells(source.to_html(index=False, escape=True,
                             border=0, na_rep='Not available')))
        self.assertIn('&lt;script&gt;', table_html(source, escape=False))

    @unittest.skipUnless(find_spec('ipywidgets'), 'Notebook widgets required')
    def test_notebook_catalog_missing_is_not_zero(self):
        from compact_report_panel import table
        source = pd.DataFrame({'source_title': ['AD paper', 'PD paper'],
                               'count': [float('nan'), 0]})
        shown = table(source)
        self.assertIn('<td>Not available</td>', shown)
        self.assertIn('<td>0.0</td>', shown)
        self.assertIsNone(MISSING_CELL.search(shown))


if __name__ == '__main__':
    unittest.main()
