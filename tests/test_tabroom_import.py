import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tabroom_import import (
    ImportRequest,
    ImportValidationError,
    infer_format,
    parse_tabroom_id,
    validate_request,
)


class RequestValidationTest(unittest.TestCase):
    def test_parses_tournament_and_event_ids(self):
        self.assertEqual(
            parse_tabroom_id(
                "https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313",
                "tourn_id",
            ),
            40313,
        )
        self.assertEqual(
            parse_tabroom_id(
                "https://www.tabroom.com/index/tourn/fields.mhtml?"
                "tourn_id=40313&event_id=383405",
                "event_id",
            ),
            383405,
        )

    def test_rejects_non_ascii_id_digits(self):
        with self.assertRaisesRegex(ImportValidationError, "numeric tourn_id"):
            parse_tabroom_id(
                "https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=²",
                "tourn_id",
            )

    def test_rejects_mismatched_tournament_ids(self):
        request = ImportRequest(
            tournament_url="https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313",
            event_url="https://www.tabroom.com/index/tourn/fields.mhtml?tourn_id=999&event_id=383405",
            slug="ukso",
            event_name="Lincoln-Douglas - TOC Bid Event",
        )
        with self.assertRaisesRegex(ImportValidationError, "tournament IDs do not match"):
            validate_request(request)

    def test_rejects_unsafe_slug(self):
        request = ImportRequest(
            tournament_url="https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313",
            event_url="https://www.tabroom.com/index/tourn/fields.mhtml?tourn_id=40313&event_id=383405",
            slug="../ukso",
            event_name="Lincoln-Douglas - TOC Bid Event",
        )
        with self.assertRaisesRegex(ImportValidationError, "slug"):
            validate_request(request)

    def test_infers_supported_formats_and_honors_override(self):
        self.assertEqual(infer_format("Lincoln-Douglas - TOC Bid Event"), "hsld")
        self.assertEqual(infer_format("Public Forum - Varsity"), "hspf")
        self.assertEqual(infer_format("Policy - Open", override="cpd"), "cpd")
        with self.assertRaisesRegex(ImportValidationError, "override"):
            infer_format("Policy - Open")
