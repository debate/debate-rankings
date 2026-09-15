# Tabroom Agent Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an AI agent import one authenticated Tabroom event from tournament URL, event URL, and slug, then validate the data and recompute the applicable rankings.

**Architecture:** The agent controls the user's authenticated browser, discovers the selected event and its published rounds, and downloads each Tabroom CSV export into a temporary directory. A deterministic Python helper parses identifiers, normalizes and validates the CSVs, installs the tournament atomically, updates the selected format config, and calls the existing ranking system. Repository instructions make the chat workflow repeatable without exposing a user-facing importer command or storing credentials.

**Tech Stack:** Python 3, pandas 2.3.3, unittest, Tabroom's authenticated web UI, existing Glicko2 ranking pipeline

**Spec:** `docs/superpowers/specs/2026-09-15-tabroom-agent-import-design.md`

## Global Constraints

- Inputs are a tournament URL, an event URL or unambiguous event context, a lowercase slug, and an optional format override.
- Supported formats are exactly `hsld`, `hspf`, and `cpd`.
- `Lincoln-Douglas` infers `hsld`; `Public Forum` infers `hspf`; ambiguous `Policy` events require an override.
- Browser navigation uses the user's authenticated Tabroom session. No credentials, cookies, or browser profile data enter the repository.
- Page requests and CSV downloads are sequential and rate-limited.
- New imports must validate completely before active tournament data or configuration changes.
- Existing slugs are never overwritten unless the user explicitly requests a refresh.
- Missing configured tournament data is an error during full-format ranking. It must never be silently skipped.
- Do not add `Signed-off-by`, `Co-Authored-By`, or AI attribution trailers other than an exact, verified `Assisted-by` value when the runtime exposes one.

---

## File Structure

- Create `AGENTS.md`: define the chat trigger, authenticated browser workflow, download rules, helper invocation, verification, and reporting contract.
- Create `src/tabroom_import.py`: own URL parsing, format inference, CSV normalization, validation, staged installation, metadata, config update, and rollback.
- Create `tests/test_tabroom_import.py`: unit and fixture-style integration tests for the deterministic importer.
- Modify `src/main.py`: expose a narrow, reusable format recomputation function while keeping the existing full application entry point.
- Modify `tests/test_ranking_statistics.py`: verify the reusable recomputation entry point and missing-input behavior.
- Modify `.gitignore`: ignore temporary local Tabroom import staging if an agent must stage inside the repository.
- Create live data at `tournaments/hsld/ukso/`: acceptance output for tournament `40313`, event `383405`.
- Modify `config/hsld-config.json`: ensure `ukso` is present once, preserving its existing chronological position.
- Regenerate applicable files under `output/`: live acceptance ranking outputs when all required inputs for the selected run are available.

---

### Task 1: Parse Requests and Infer Ranking Format

**Files:**

- Create: `src/tabroom_import.py`
- Create: `tests/test_tabroom_import.py`

**Interfaces:**

- Consumes: tournament URL, event URL, slug, optional format override, and rendered event name.
- Produces: `ImportRequest`, `parse_tabroom_id(url, parameter)`, `validate_request(request)`, and `infer_format(event_name, override=None)`.

- [ ] **Step 1: Write failing tests for identifiers, slugs, and format inference**

```python
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
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import.RequestValidationTest -v`

Expected: FAIL because `tabroom_import` does not exist.

- [ ] **Step 3: Implement immutable request parsing and validation**

```python
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

SUPPORTED_FORMATS = {"hsld", "hspf", "cpd"}


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportRequest:
    tournament_url: str
    event_url: str
    slug: str
    event_name: str
    format_override: str | None = None


def parse_tabroom_id(url: str, parameter: str) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"tabroom.com", "www.tabroom.com"}:
        raise ImportValidationError("URL must be an HTTPS Tabroom URL")
    values = parse_qs(parsed.query).get(parameter, [])
    if len(values) != 1 or not values[0].isdigit():
        raise ImportValidationError(f"URL must contain one numeric {parameter}")
    return int(values[0])


def infer_format(event_name: str, override: str | None = None) -> str:
    if override is not None:
        if override not in SUPPORTED_FORMATS:
            raise ImportValidationError(f"unsupported format override: {override}")
        return override
    if "Lincoln-Douglas" in event_name:
        return "hsld"
    if "Public Forum" in event_name:
        return "hspf"
    if "Policy" in event_name:
        raise ImportValidationError("Policy events require a format override")
    raise ImportValidationError(f"cannot infer format from event: {event_name}")


def validate_request(request: ImportRequest) -> tuple[int, int, str]:
    tournament_id = parse_tabroom_id(request.tournament_url, "tourn_id")
    event_tournament_id = parse_tabroom_id(request.event_url, "tourn_id")
    if tournament_id != event_tournament_id:
        raise ImportValidationError("tournament IDs do not match")
    event_id = parse_tabroom_id(request.event_url, "event_id")
    if not request.slug or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in request.slug
    ):
        raise ImportValidationError("slug must contain lowercase letters, numbers, and hyphens")
    return tournament_id, event_id, infer_format(request.event_name, request.format_override)
```

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import.RequestValidationTest -v`

Expected: all request validation tests PASS.

- [ ] **Step 5: Commit the request contract**

```bash
git add src/tabroom_import.py tests/test_tabroom_import.py
git commit -m "Add Tabroom import request validation"
```

---

### Task 2: Normalize and Validate Downloaded Tabroom CSVs

**Files:**

- Modify: `src/tabroom_import.py`
- Modify: `tests/test_tabroom_import.py`

**Interfaces:**

- Consumes: exported field CSV path and `DownloadedRound` objects containing ordinal, round ID, name, and CSV path.
- Produces: `normalize_entries(path) -> pandas.DataFrame`, `normalize_round(path) -> pandas.DataFrame`, and `validate_dataset(entries, rounds) -> None`.

- [ ] **Step 1: Add failing normalization and dataset validation tests**

```python
import tempfile
import pandas as pd

from tabroom_import import DownloadedRound, normalize_entries, normalize_round, validate_dataset


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
```

- [ ] **Step 2: Run dataset tests and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import.DatasetValidationTest -v`

Expected: FAIL because normalization and dataset validation interfaces do not exist.

- [ ] **Step 3: Implement round descriptors and CSV normalization**

```python
from pathlib import Path
import pandas as pd


@dataclass(frozen=True)
class DownloadedRound:
    ordinal: int
    round_id: int
    name: str
    path: Path
    data: pd.DataFrame | None = None


def _clean_columns(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    cleaned.columns = [" ".join(str(column).split()) for column in cleaned.columns]
    return cleaned


def normalize_entries(path: Path) -> pd.DataFrame:
    entries = _clean_columns(pd.read_csv(path, keep_default_na=False))
    required = ["Institution", "Location", "Entry", "Code"]
    missing = [column for column in required if column not in entries.columns]
    if missing:
        raise ImportValidationError(f"field export missing columns: {', '.join(missing)}")
    for column in required:
        entries[column] = entries[column].astype(str).str.strip()
    return entries


def normalize_round(path: Path) -> pd.DataFrame:
    round_data = _clean_columns(pd.read_csv(path, keep_default_na=False))
    round_data = round_data.rename(columns={"Pro": "Aff", "Con": "Neg"})
    required = ["Aff", "Neg", "Win"]
    missing = [column for column in required if column not in round_data.columns]
    if missing:
        raise ImportValidationError(f"round export missing columns: {', '.join(missing)}")
    for column in required:
        round_data[column] = round_data[column].astype(str).str.strip()
    return round_data
```

- [ ] **Step 4: Implement complete dataset validation**

```python
def validate_dataset(entries: pd.DataFrame, rounds: list[DownloadedRound]) -> None:
    if entries.empty:
        raise ImportValidationError("field export is empty")
    if entries["Code"].eq("").any() or entries["Code"].duplicated().any():
        raise ImportValidationError("entry codes must be nonempty and unique")
    if not rounds:
        raise ImportValidationError("event has no published round results")
    round_ids = [round_item.round_id for round_item in rounds]
    ordinals = [round_item.ordinal for round_item in rounds]
    if len(round_ids) != len(set(round_ids)):
        raise ImportValidationError("round IDs must be unique")
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise ImportValidationError("round ordinals must be unique and sorted")

    known_codes = set(entries["Code"])
    for round_item in rounds:
        data = round_item.data if round_item.data is not None else normalize_round(round_item.path)
        for column in ("Aff", "Neg"):
            for code in data[column]:
                if not code or "bye" in code.lower():
                    continue
                if code not in known_codes:
                    raise ImportValidationError(
                        f"round {round_item.round_id} contains unknown entry code: {code}"
                    )
        valid_winners = data["Win"].str.lower().isin({"", "aff", "neg", "pro", "con"})
        if not valid_winners.all():
            bad_winner = data.loc[~valid_winners, "Win"].iloc[0]
            raise ImportValidationError(
                f"round {round_item.round_id} contains unsupported winner: {bad_winner}"
            )
```

- [ ] **Step 5: Run normalization tests and the existing suite**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import.DatasetValidationTest -v`

Expected: dataset tests PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit CSV normalization and validation**

```bash
git add src/tabroom_import.py tests/test_tabroom_import.py
git commit -m "Validate Tabroom field and round exports"
```

---

### Task 3: Stage and Install a Tournament Atomically

**Files:**

- Modify: `src/tabroom_import.py`
- Modify: `tests/test_tabroom_import.py`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: project root, validated `ImportRequest`, field export, downloaded rounds, and tournament display name.
- Produces: `install_import(..., replace_existing=False) -> InstalledImport`, normalized tournament files, `tabroom.json`, and one idempotent config entry.

- [ ] **Step 1: Add failing tests for filenames, metadata, config idempotence, and collision safety**

```python
import json

from tabroom_import import install_import


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
```

Add these concrete helpers above `InstallImportTest`:

```python
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
```

- [ ] **Step 2: Run install tests and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import.InstallImportTest -v`

Expected: FAIL because `install_import` does not exist.

- [ ] **Step 3: Implement deterministic filenames and metadata**

```python
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone


@dataclass(frozen=True)
class InstalledImport:
    target: Path
    format_name: str
    entry_count: int
    round_count: int


def round_filename(round_item: DownloadedRound) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", round_item.name.lower()).strip("-")
    return f"{round_item.ordinal:02d}-{normalized}-{round_item.round_id}.csv"


def _metadata(request, tournament_name, tournament_id, event_id, format_name, rounds):
    return {
        "tournament_name": tournament_name,
        "tournament_url": request.tournament_url,
        "tournament_id": tournament_id,
        "event_name": request.event_name,
        "event_url": request.event_url,
        "event_id": event_id,
        "format": format_name,
        "slug": request.slug,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "rounds": [
            {"ordinal": item.ordinal, "name": item.name, "round_id": item.round_id}
            for item in rounds
        ],
    }
```

- [ ] **Step 4: Implement staged installation and idempotent config update**

```python
def install_import(
    project_root: Path,
    request: ImportRequest,
    tournament_name: str,
    field_path: Path,
    rounds: list[DownloadedRound],
    replace_existing: bool = False,
) -> InstalledImport:
    tournament_id, event_id, format_name = validate_request(request)
    entries = normalize_entries(field_path)
    loaded_rounds = [
        DownloadedRound(item.ordinal, item.round_id, item.name, item.path, normalize_round(item.path))
        for item in rounds
    ]
    validate_dataset(entries, loaded_rounds)

    target = project_root / "tournaments" / format_name / request.slug
    if target.exists() and not replace_existing:
        raise FileExistsError(f"tournament slug already exists: {request.slug}")
    config_path = project_root / "config" / f"{format_name}-config.json"
    original_config_text = config_path.read_text()
    config = json.loads(original_config_text)
    if request.slug not in config["tournaments"]:
        config["tournaments"].append(request.slug)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = project_root / ".tabroom-import"
    staging_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging_parent) as directory:
        temporary_root = Path(directory)
        staged = temporary_root / request.slug
        backup = temporary_root / f"{request.slug}-backup"
        staged.mkdir()
        entries.to_csv(staged / "entries.csv", index=False)
        for item in loaded_rounds:
            item.data.to_csv(staged / round_filename(item), index=False)
        (staged / "tabroom.json").write_text(
            json.dumps(
                _metadata(request, tournament_name, tournament_id, event_id, format_name, loaded_rounds),
                indent=2,
            )
            + "\n"
        )
        had_existing_target = target.exists()
        if had_existing_target:
            target.replace(backup)
        staged.replace(target)

        try:
            temporary_config = config_path.with_suffix(".json.tmp")
            temporary_config.write_text(json.dumps(config, indent=2) + "\n")
            temporary_config.replace(config_path)
        except Exception:
            shutil.rmtree(target)
            if had_existing_target:
                backup.replace(target)
            config_path.write_text(original_config_text)
            raise

    return InstalledImport(target, format_name, len(entries), len(loaded_rounds))
```

- [ ] **Step 5: Ignore only local import staging**

Add this line to `.gitignore`:

```gitignore
.tabroom-import/
```

- [ ] **Step 6: Run importer tests and the full suite**

Run: `.venv/bin/python -m unittest tests.test_tabroom_import -v`

Expected: importer tests PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit atomic installation**

```bash
git add .gitignore src/tabroom_import.py tests/test_tabroom_import.py
git commit -m "Install validated Tabroom tournaments atomically"
```

---

### Task 4: Expose Safe Ranking Recalculation

**Files:**

- Modify: `src/main.py`
- Modify: `tests/test_ranking_statistics.py`

**Interfaces:**

- Consumes: project root, format name, optional tournament subset, and output prefix.
- Produces: `validate_tournament_inputs(...)` and `recompute_format(...)`, both reusable by an agent after import.

- [ ] **Step 1: Add failing tests for missing inputs and a selected-tournament recomputation**

```python
from main import recompute_format, validate_tournament_inputs


class RecomputeFormatTest(unittest.TestCase):
    def test_reports_every_missing_configured_tournament(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"tournaments": ["one", "two"]}))
            with self.assertRaisesRegex(FileNotFoundError, "one, two"):
                validate_tournament_inputs(root, "hsld", config_path, ["one", "two"])

    def test_recomputes_an_explicit_tournament_subset(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = build_test_ranking_project(Path(temporary_directory))
            recompute_format(
                project_root=root,
                config_path=root / "config.json",
                format_name="test-format",
                output_prefix="test_",
                tournaments=["invitational"],
            )
            self.assertTrue((root / "output" / "test_rankings.csv").exists())
```

Add this concrete fixture helper above `RecomputeFormatTest`, then refactor the existing statistics test to use it:

```python
def build_test_ranking_project(root: Path) -> Path:
    tournament = root / "tournaments" / "test-format" / "invitational"
    tournament.mkdir(parents=True)
    (root / "output").mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "tournaments": ["invitational"],
                "majors": [],
                "multi_team_debaters": [],
            }
        )
    )
    pd.DataFrame([
        {"Institution": "Alpha", "Entry": "Alice", "Code": "Alpha A"},
        {"Institution": "Beta", "Entry": "Bob", "Code": "Beta B"},
    ]).to_csv(tournament / "entries.csv", index=False)
    pd.DataFrame([
        {"Aff": "Alpha A", "Neg": "Beta B", "Judge": "J1", "Win": "Aff"}
    ]).to_csv(tournament / "01-round-1.csv", index=False)
    return root
```

- [ ] **Step 2: Run recomputation tests and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_ranking_statistics.RecomputeFormatTest -v`

Expected: FAIL because the reusable functions do not exist.

- [ ] **Step 3: Implement input validation without silent skipping**

```python
from pathlib import Path


def validate_tournament_inputs(
    project_root: Path,
    format_name: str,
    config_path: Path,
    tournaments: list[str],
) -> None:
    missing = []
    for tournament in tournaments:
        directory = project_root / "tournaments" / format_name / tournament
        if not (directory / "entries.csv").is_file():
            missing.append(tournament)
    if missing:
        raise FileNotFoundError(
            f"missing tournament data for {format_name}: {', '.join(missing)}"
        )
```

- [ ] **Step 4: Implement a reusable recomputation wrapper**

```python
def recompute_format(
    project_root: Path,
    config_path: Path,
    format_name: str,
    output_prefix: str,
    tournaments: list[str] | None = None,
) -> None:
    config = load_config(str(config_path))
    selected = tournaments if tournaments is not None else config.get("tournaments", [])
    validate_tournament_inputs(project_root, format_name, config_path, selected)
    previous_directory = Path.cwd()
    try:
        os.chdir(project_root)
        RankingSystem(str(config_path), format_name).run(output_prefix, tournaments=selected)
    finally:
        os.chdir(previous_directory)
```

Update `main()` to call `recompute_format` for each full-format run. Keep topic-specific LD runs unchanged except for calling the same wrapper with their explicit tournament subsets.

- [ ] **Step 5: Run ranking tests and the full suite**

Run: `.venv/bin/python -m unittest tests.test_ranking_statistics -v`

Expected: ranking tests PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit reusable ranking recalculation**

```bash
git add src/main.py tests/test_ranking_statistics.py
git commit -m "Add validated format ranking recalculation"
```

---

### Task 5: Document the Chat-Driven Agent Workflow

**Files:**

- Create: `AGENTS.md`

**Interfaces:**

- Consumes: chat messages containing tournament URL, event URL or context, slug, and optional format override.
- Produces: a repeatable agent procedure that uses the browser and deterministic helper from Tasks 1 through 4.

- [ ] **Step 1: Write repository instructions with an exact trigger and safety contract**

Create `AGENTS.md` with these requirements:

```markdown
# Debate rankings agent instructions

## Tabroom event imports

Treat a request containing a Tabroom tournament URL, event URL or event name, and slug as an instruction to complete the import end to end.

1. Read `docs/superpowers/specs/2026-09-15-tabroom-agent-import-design.md` before importing.
2. Parse the IDs with `src/tabroom_import.py`. If `event_id` is absent and context does not identify exactly one event, ask the user which event to use.
3. Infer `hsld` from Lincoln-Douglas and `hspf` from Public Forum. Require an override for ambiguous Policy events. Honor an explicit override.
4. Use the user's authenticated Tabroom browser session. If Tabroom shows its login page, ask the user to log in and resume afterward. Never save credentials, cookies, or browser profile data.
5. Verify the tournament heading, event heading, IDs, and published entry count before downloading.
6. On the event field page, use Tabroom's CSV export button. On the results index for the same event, collect only `round_results.mhtml` links for that event. Download their CSV exports sequentially in chronological order, waiting at least one second between downloads.
7. Prefer Tabroom's own CSV exports. If an export control is unavailable, extract the rendered table without inventing values. Stop if required columns are absent.
8. Stage downloads outside the tournament target. Use the deterministic importer to normalize, validate, write metadata, install files, and update config. Never overwrite an existing slug unless the user explicitly requested a refresh.
9. Run the unit tests. Recompute the selected format across its configured tournament list only when all configured inputs exist. If unrelated configured data is missing, report the exact missing slugs and also validate the new tournament with an explicit single-tournament ranking run. Never silently omit configured tournaments from a claimed full ranking.
10. Report tournament name, event name, inferred or overridden format, entry count, round count, target directory, config status, test result, and whether the ranking was full-format or import-only validation.

For web requests outside browser automation, use the user agent `OpenAI File Downloader, XaiImageApiFetch/1.0`.
Do not add `Signed-off-by` or `Co-Authored-By` trailers. Add `Assisted-by` only when the exact runtime model identifier is available from session context.
```

- [ ] **Step 2: Review the instructions against the design acceptance criteria**

Run: `rg -n "credentials|sequentially|overwrite|Recompute|Report|event_id|override" AGENTS.md`

Expected: every required workflow area appears at least once.

- [ ] **Step 3: Check formatting and commit**

Run: `git diff --check`

Expected: no whitespace errors.

```bash
git add AGENTS.md
git commit -m "Document agent-driven Tabroom imports"
```

---

### Task 6: Run the Live UKSO Acceptance Import

**Files:**

- Create: `tournaments/hsld/ukso/entries.csv`
- Create: `tournaments/hsld/ukso/01-round-1-1543295.csv`
- Create: remaining ordered round CSVs through Finals
- Create: `tournaments/hsld/ukso/tabroom.json`
- Modify only if needed: `config/hsld-config.json`
- Regenerate when full inputs are available: `output/hsld_rankings.csv`, `output/hsld_full_rankings.csv`, `output/hsld_field_statistics.csv`, and LD topic outputs selected by the existing configuration

**Interfaces:**

- Consumes: tournament `40313`, event `383405`, slug `ukso`, authenticated browser access, and Tasks 1 through 5.
- Produces: the first real imported tournament and evidence that the full agent workflow works.

- [ ] **Step 1: Confirm the live source before downloading**

Open the tournament and event pages and verify these exact values:

```text
Tournament ID: 40313
Tournament: National Speech and Debate Season Opener
Event ID: 383405
Event: Lincoln-Douglas - TOC Bid Event
Expected format: hsld
Expected published field count: 231
Expected published round count: 13
```

If Tabroom shows a login page, ask the user to log in and resume. If any source value differs, stop and report the mismatch.

- [ ] **Step 2: Download the field and discover the published rounds**

Use the event field CSV export. From the event's results index, record the chronological rounds and IDs:

```text
1 Round 1 1543295
2 Round 2 1543296
3 Round 3 1528673
4 Round 4 1528674
5 Round 5 1528675
6 Round 6 1528676
7 Runoff 1543297
8 Triples 1528677
9 Doubles 1528678
10 Octafinals 1528679
11 Quarterfinals 1528680
12 Semifinals 1528681
13 Finals 1543298
```

Download each round CSV sequentially with at least a one-second interval.

- [ ] **Step 3: Normalize, validate, and install the import**

Construct `ImportRequest` with the event-specific URL:

```python
request = ImportRequest(
    tournament_url="https://www.tabroom.com/index/tourn/index.mhtml?tourn_id=40313",
    event_url="https://www.tabroom.com/index/tourn/fields.mhtml?tourn_id=40313&event_id=383405",
    slug="ukso",
    event_name="Lincoln-Douglas - TOC Bid Event",
)
```

Call `install_import` with the downloaded field and 13 `DownloadedRound` descriptors. Expected result:

```text
format_name: hsld
entry_count: 231
round_count: 13
target: tournaments/hsld/ukso
```

Because `ukso` is already present in the current HS LD config, verify that its position and count remain unchanged.

- [ ] **Step 4: Run automated tests**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Validate ranking behavior against current repository inputs**

First run the explicit imported-tournament validation:

```python
recompute_format(
    project_root=Path.cwd(),
    config_path=Path("config/hsld-config.json"),
    format_name="hsld",
    output_prefix="hsld_ukso_validation_",
    tournaments=["ukso"],
)
```

Expected: the `ukso` tournament processes successfully and produces nonempty validation ranking CSVs.

Then call `validate_tournament_inputs` with the complete HS LD config. If it passes, run the full configured HS LD recomputation and verify the normal HS LD output files are nonempty. If it reports missing tournament data, do not skip those tournaments and do not replace the normal HS LD outputs. Report the missing slugs and retain the separate `ukso` validation outputs as evidence that the import is sound.

- [ ] **Step 6: Inspect imported and generated data**

Run these checks:

```bash
wc -l tournaments/hsld/ukso/entries.csv tournaments/hsld/ukso/*.csv
python -m json.tool tournaments/hsld/ukso/tabroom.json
git diff --check
git status --short
```

Expected:

- `entries.csv` has 232 lines including its header.
- Exactly 13 round CSV files are present.
- Metadata names all 13 unique round IDs in ordinal order.
- No whitespace errors appear.
- No credentials, cookies, browser state, or temporary downloads appear in `git status`.

- [ ] **Step 7: Commit the acceptance import and valid outputs**

Review the exact status first. Add only the imported `ukso` directory, any idempotent config change, and ranking outputs that were successfully regenerated from complete inputs.

```bash
git add tournaments/hsld/ukso config/hsld-config.json
git commit -m "Import UKSO varsity LD results"
```

Do not add temporary validation ranking outputs to the commit. Do not add the unrelated existing untracked `tournaments/hsld/loyola` or `tournaments/hsld/loyola-rr` directories.
