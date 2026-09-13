import unittest

from electricity_optimizer.models import PDFPage, TableCell
from electricity_optimizer.extraction import citation_matches


class LayoutTests(unittest.TestCase):
    def test_match_inside_cell_but_not_across_cells(self):
        page = PDFPage(page_number=1, text="Question interrupted answer", needs_review=False,
            table_cells=[TableCell(table_number=1, row_number=1, column_number=1,
                bbox=(0, 0, 10, 10), text="Moving exception applies"),
                TableCell(table_number=1, row_number=1, column_number=2,
                bbox=(10, 0, 20, 10), text="with evidence")])
        self.assertTrue(citation_matches("Moving exception\napplies", page))
        self.assertFalse(citation_matches("Moving exception applies with evidence", page))
        self.assertFalse(citation_matches("Moving exception never applies", page))

    def test_plain_text_fallback_and_legacy_models(self):
        page = PDFPage(page_number=1, text="Contract term: 12 months", needs_review=False)
        self.assertEqual(citation_matches("Contract term: 12 months", page), ["page text"])
