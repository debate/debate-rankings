import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

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


@dataclass(frozen=True)
class DownloadedRound:
    ordinal: int
    round_id: int
    name: str
    path: Path
    data: pd.DataFrame | None = None


@dataclass(frozen=True)
class InstalledImport:
    target: Path
    format_name: str
    entry_count: int
    round_count: int


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
        valid_winners = data["Win"].apply(
            lambda winner: pd.isna(winner)
            or not str(winner).strip()
            or any(side in str(winner).lower() for side in ("aff", "neg", "pro", "con"))
        )
        if not valid_winners.all():
            bad_winner = data.loc[~valid_winners, "Win"].iloc[0]
            raise ImportValidationError(
                f"round {round_item.round_id} contains unsupported winner: {bad_winner}"
            )


def parse_tabroom_id(url: str, parameter: str) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"tabroom.com", "www.tabroom.com"}:
        raise ImportValidationError("URL must be an HTTPS Tabroom URL")
    values = parse_qs(parsed.query).get(parameter, [])
    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
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


def round_filename(round_item: DownloadedRound) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", round_item.name.lower()).strip("-")
    return f"{round_item.ordinal:02d}-{normalized}-{round_item.round_id}.csv"


def _metadata(
    request: ImportRequest,
    tournament_name: str,
    tournament_id: int,
    event_id: int,
    format_name: str,
    rounds: list[DownloadedRound],
) -> dict:
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
        DownloadedRound(
            item.ordinal,
            item.round_id,
            item.name,
            item.path,
            normalize_round(item.path),
        )
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
                _metadata(
                    request,
                    tournament_name,
                    tournament_id,
                    event_id,
                    format_name,
                    loaded_rounds,
                ),
                indent=2,
            )
            + "\n"
        )

        had_existing_target = target.exists()
        try:
            if had_existing_target:
                target.replace(backup)
            staged.replace(target)

            temporary_config = config_path.with_suffix(".json.tmp")
            temporary_config.write_text(json.dumps(config, indent=2) + "\n")
            temporary_config.replace(config_path)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if had_existing_target and backup.exists():
                backup.replace(target)
            config_path.write_text(original_config_text)
            raise

    return InstalledImport(target, format_name, len(entries), len(loaded_rounds))
