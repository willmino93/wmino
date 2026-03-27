"""
lib/yaml_handler.py

Load, save, and validate resume.yaml.
"""

import yaml


REQUIRED_TOP_KEYS = {"subheader", "summary", "core_competencies", "technical_proficiencies", "bullets"}
REQUIRED_BULLET_KEYS = {"truecar", "ekn", "pfizer", "tanabe"}


def load_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def save_yaml(path: str, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def validate_yaml(data: dict) -> None:
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"resume.yaml is missing required keys: {missing}")

    if not isinstance(data["subheader"], str):
        raise ValueError("'subheader' must be a string")

    if not isinstance(data["summary"], str):
        raise ValueError("'summary' must be a string")

    if not isinstance(data["core_competencies"], list) or not all(
        isinstance(row, list) for row in data["core_competencies"]
    ):
        raise ValueError("'core_competencies' must be a list of lists")

    if not isinstance(data["technical_proficiencies"], list) or not all(
        isinstance(row, list) for row in data["technical_proficiencies"]
    ):
        raise ValueError("'technical_proficiencies' must be a list of lists")

    bullets = data.get("bullets", {})
    if not isinstance(bullets, dict):
        raise ValueError("'bullets' must be a dict")

    missing_companies = REQUIRED_BULLET_KEYS - set(bullets.keys())
    if missing_companies:
        raise ValueError(f"'bullets' is missing company keys: {missing_companies}")

    for company in REQUIRED_BULLET_KEYS:
        if not isinstance(bullets[company], list):
            raise ValueError(f"'bullets.{company}' must be a list of strings")
