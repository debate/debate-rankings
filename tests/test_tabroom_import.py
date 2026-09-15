import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tabroom_import import (
    DownloadedRound,
    ImportRequest,
    ImportValidationError,
    infer_format,
    install_import,
    normalize_entries,
    normalize_round,
    parse_tabroom_id,
    validate_dataset,
    validate_request,
)


def make_ukso_request() -> ImportRequest:
    return ImportRequest(
        tournament_url="https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313",
        event_url=(
            "https://www.tabroom.com/index/tourn/fields.mhtml?"
            "tourn_id=40313&event_id=383405"
        ),
        slug="ukso",
        event_name="Lincoln-Douglas - TOC Bid Event",
    )


def make_valid_exports(root: Path) -> tuple[Path, list[DownloadedRound]]:
    field_path = root / "field.csv"
    round_path = root / "round.csv"
    pd.DataFrame([
        {
            "Institution": "Able2Shine",
            "Location": "CA/US",
            "Entry": "Avery Feng",
            "Code": "Able2Shine AF",
        },
        {
            "Institution": "Harker",
            "Location": "CA/US",
            "Entry": "Aman Ahmed",
            "Code": "Harker AA",
        },
    ]).to_csv(field_path, index=False)
    pd.DataFrame([
        {"Aff": "Able2Shine AF", "Neg": "Harker AA", "Judge": "J", "Win": "Aff"}
    ]).to_csv(round_path, index=False)
    return field_path, [
        DownloadedRound(
            ordinal=1,
            round_id=1543295,
            name="Round 1",
            path=round_path,
        )
    ]


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

    def test_accepts_tabroom_score_with_neg_winner(self):
        entries = pd.DataFrame([
            {"Institution": "A", "Location": "CA/US", "Entry": "A One", "Code": "A 1"},
            {"Institution": "B", "Location": "CA/US", "Entry": "B Two", "Code": "B 2"},
        ])
        round_item = DownloadedRound(
            1, 1, "Round 1", Path("round.csv"),
            pd.DataFrame([{"Aff": "A 1", "Neg": "B 2", "Win": "2-0\tNEG"}]),
        )

        validate_dataset(entries, [round_item])

    def test_accepts_missing_winner_without_attribute_error(self):
        entries = pd.DataFrame([
            {"Institution": "A", "Location": "CA/US", "Entry": "A One", "Code": "A 1"},
            {"Institution": "B", "Location": "CA/US", "Entry": "B Two", "Code": "B 2"},
        ])
        round_item = DownloadedRound(
            1, 1, "Round 1", Path("round.csv"),
            pd.DataFrame([{"Aff": "A 1", "Neg": "B 2", "Win": float("nan")}]),
        )

        validate_dataset(entries, [round_item])


class InstallImportTest(unittest.TestCase):
    def test_installs_ordered_files_metadata_and_one_config_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "hsld-config.json").write_text(
                json.dumps({"tournaments": ["loyola", "ukso"], "majors": [], "multi_team_debaters": []})
            )
            field_path, rounds = make_valid_exports(root)
            request = make_ukso_request()

            installed = install_import(root, request, "National Speech and Debate Season Opener", field_path, rounds)

            target = root / "tournaments" / "hsld" / "ukso"
            self.assertEqual(installed.target, target)
            self.assertTrue((target / "entries.csv").exists())
            self.assertTrue((target / "01-round-1-1543295.csv").exists())
            metadata = json.loads((target / "tabroom.json").read_text())
            self.assertEqual(metadata["event_id"], 383405)
            config = json.loads((root / "config" / "hsld-config.json").read_text())
            self.assertEqual(config["tournaments"].count("ukso"), 1)

    def test_refuses_to_replace_existing_slug(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "tournaments" / "hsld" / "ukso"
            target.mkdir(parents=True)
            (target / "keep.txt").write_text("user data")
            field_path, rounds = make_valid_exports(root)

            with self.assertRaisesRegex(FileExistsError, "ukso"):
                install_import(root, make_ukso_request(), "Season Opener", field_path, rounds)

            self.assertEqual((target / "keep.txt").read_text(), "user data")

    def test_replaces_existing_slug_only_when_refresh_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "hsld-config.json").write_text(
                json.dumps({"tournaments": ["ukso"], "majors": [], "multi_team_debaters": []})
            )
            target = root / "tournaments" / "hsld" / "ukso"
            target.mkdir(parents=True)
            (target / "obsolete.csv").write_text("old data")
            field_path, rounds = make_valid_exports(root)

            install_import(
                root,
                make_ukso_request(),
                "Season Opener",
                field_path,
                rounds,
                replace_existing=True,
            )

            self.assertFalse((target / "obsolete.csv").exists())
            self.assertTrue((target / "entries.csv").exists())

    def test_refresh_restores_target_and_config_when_staged_install_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config" / "hsld-config.json"
            config_path.parent.mkdir()
            original_config = json.dumps({"tournaments": ["loyola"], "majors": [], "multi_team_debaters": []})
            config_path.write_text(original_config)
            target = root / "tournaments" / "hsld" / "ukso"
            target.mkdir(parents=True)
            (target / "keep.txt").write_text("user data")
            field_path, rounds = make_valid_exports(root)
            original_replace = Path.replace

            def fail_staged_install(source: Path, destination: Path):
                if source.name == "ukso" and destination == target:
                    raise OSError("install failed")
                return original_replace(source, destination)

            with patch.object(Path, "replace", autospec=True, side_effect=fail_staged_install):
                with self.assertRaisesRegex(OSError, "install failed"):
                    install_import(
                        root,
                        make_ukso_request(),
                        "Season Opener",
                        field_path,
                        rounds,
                        replace_existing=True,
                    )

            self.assertEqual((target / "keep.txt").read_text(), "user data")
            self.assertEqual(config_path.read_text(), original_config)

    def test_refresh_keeps_original_target_when_backup_creation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config" / "hsld-config.json"
            config_path.parent.mkdir()
            original_config = json.dumps({"tournaments": ["loyola"], "majors": [], "multi_team_debaters": []})
            config_path.write_text(original_config)
            target = root / "tournaments" / "hsld" / "ukso"
            target.mkdir(parents=True)
            (target / "keep.txt").write_text("user data")
            field_path, rounds = make_valid_exports(root)
            original_replace = Path.replace

            def fail_backup_creation(source: Path, destination: Path):
                if source == target and destination.name == "ukso-backup":
                    raise OSError("backup failed")
                return original_replace(source, destination)

            with patch.object(Path, "replace", autospec=True, side_effect=fail_backup_creation):
                with self.assertRaisesRegex(OSError, "backup failed"):
                    install_import(
                        root,
                        make_ukso_request(),
                        "Season Opener",
                        field_path,
                        rounds,
                        replace_existing=True,
                    )

            self.assertEqual((target / "keep.txt").read_text(), "user data")
            self.assertEqual(config_path.read_text(), original_config)

    def test_refuses_slug_claimed_before_atomic_target_create_without_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config" / "hsld-config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"tournaments": ["loyola"], "majors": [], "multi_team_debaters": []})
            )
            target = root / "tournaments" / "hsld" / "ukso"
            field_path, rounds = make_valid_exports(root)
            original_mkdir = Path.mkdir

            def create_competing_target(path: Path, *args, **kwargs):
                if path == target:
                    original_mkdir(path)
                    (target / "keep.txt").write_text("user data")
                return original_mkdir(path, *args, **kwargs)

            with patch.object(Path, "mkdir", autospec=True, side_effect=create_competing_target):
                with self.assertRaisesRegex(FileExistsError, "ukso"):
                    install_import(root, make_ukso_request(), "Season Opener", field_path, rounds)

            self.assertEqual((target / "keep.txt").read_text(), "user data")
