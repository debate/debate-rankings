import json
from datetime import date


def load_config(config_path: str):
    """Loads json config file from string passed.

    "tournaments" maps slug -> ISO start date; it is returned as a list of
    slugs sorted by date. Ties keep file order (stable sort), so a round robin
    listed before its main tournament still runs first.
    """
    with open(config_path) as config_file:
        config = json.load(config_file)
    tournaments = config.get("tournaments", {})
    config["tournaments"] = sorted(
        tournaments, key=lambda slug: date.fromisoformat(tournaments[slug])
    )
    return config
