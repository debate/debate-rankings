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
