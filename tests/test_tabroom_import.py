import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tabroom_import import (
    DownloadedRound,
    ImportRequest,
    ImportValidationError,
    infer_format,
    normalize_entries,
    normalize_round,
    parse_tabroom_id,
    validate_dataset,
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


class DatasetValidationTest(unittest.TestCase):
    def test_normalizes_exported_field_and_round_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([
                {
                    " Institution ": "Able2Shine",
                    "Location": "CA/US",
                    "Entry": "Avery Feng",
                    "Code": "Able2Shine AF",
                    "Status": "",
                    "Record": "",
                }
            ]).to_csv(root / "field.csv", index=False)
            pd.DataFrame([
                {"Aff": "Able2Shine AF", "Neg": "Harker AA", "Judge": "J", "Win": "Aff"}
            ]).to_csv(root / "round.csv", index=False)

            entries = normalize_entries(root / "field.csv")
            round_data = normalize_round(root / "round.csv")

            self.assertEqual(list(entries.columns[:4]), ["Institution", "Location", "Entry", "Code"])
            self.assertEqual(round_data.loc[0, "Win"], "Aff")

    def test_normalizes_pro_and_con_to_aff_and_neg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "round.csv"
            pd.DataFrame([{"Pro": "A", "Con": "B", "Win": "Pro"}]).to_csv(path, index=False)

            round_data = normalize_round(path)

            self.assertEqual(list(round_data.columns), ["Aff", "Neg", "Win"])
            self.assertEqual(round_data.loc[0, "Aff"], "A")

    def test_rejects_unknown_non_bye_entry_code(self):
        entries = pd.DataFrame([
            {"Institution": "Able2Shine", "Location": "CA/US", "Entry": "Avery Feng", "Code": "Able2Shine AF"},
            {"Institution": "Harker", "Location": "CA/US", "Entry": "Aman Ahmed", "Code": "Harker AA"},
        ])
        bad_round = DownloadedRound(
            ordinal=1,
            round_id=1543295,
            name="Round 1",
            path=Path("round.csv"),
            data=pd.DataFrame([{"Aff": "Missing XX", "Neg": "Harker AA", "Win": "Neg"}]),
        )
        with self.assertRaisesRegex(ImportValidationError, "Missing XX"):
            validate_dataset(entries, [bad_round])

    def test_rejects_duplicate_or_blank_entry_codes(self):
        entries = pd.DataFrame([
            {"Institution": "A", "Location": "CA/US", "Entry": "A One", "Code": "A 1"},
            {"Institution": "B", "Location": "CA/US", "Entry": "B Two", "Code": "A 1"},
        ])
        with self.assertRaisesRegex(ImportValidationError, "nonempty and unique"):
            validate_dataset(entries, [DownloadedRound(1, 1, "Round 1", Path("round.csv"), pd.DataFrame([
                {"Aff": "A 1", "Neg": "bye", "Win": "Aff"}
            ]))])

    def test_rejects_unsupported_winner(self):
        entries = pd.DataFrame([{"Institution": "A", "Location": "CA/US", "Entry": "A One", "Code": "A 1"}])
        round_item = DownloadedRound(
            1, 1, "Round 1", Path("round.csv"),
            pd.DataFrame([{"Aff": "A 1", "Neg": "bye", "Win": "Judge"}]),
        )
        with self.assertRaisesRegex(ImportValidationError, "unsupported winner: Judge"):
            validate_dataset(entries, [round_item])
