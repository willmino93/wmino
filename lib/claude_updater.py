"""
lib/claude_updater.py

Uses the Anthropic Claude API to interpret a natural-language resume update
request and return an updated resume.yaml.

Flow:
  1. Load current resume.yaml
  2. Send YAML + user request to Claude
  3. Claude returns the complete updated YAML (no prose)
  4. Validate, print diff, save

Usage:
  from lib.claude_updater import apply_update
  updated = apply_update("Add a TrueCar bullet about improving load time by 40%", config)
"""

import os
import anthropic
import yaml

from lib.yaml_handler import load_yaml, save_yaml, validate_yaml


SYSTEM_PROMPT = """\
You are a resume editor. The user will give you their current resume as YAML \
and describe one or more changes to make. Your job is to output the complete \
updated resume as valid YAML — nothing else. No explanation, no markdown fences, \
no commentary. Output only the raw YAML.

Schema rules (do not change the structure):
  subheader: string
  summary: string (single paragraph, no line breaks)
  core_competencies: list of lists — each inner list has exactly 3 string items; \
max 4 rows
  technical_proficiencies: list of lists — distribute items evenly across exactly \
2 rows
  bullets:
    truecar: list of strings
    ekn: list of strings
    pfizer: list of strings
    tanabe: list of strings

Only modify what the user asks. Keep all other content identical.
"""


def _build_user_message(current_yaml_str: str, user_request: str) -> str:
    return (
        f"Current resume YAML:\n\n{current_yaml_str}\n\n"
        f"Update request:\n{user_request.strip()}"
    )


def _yaml_to_str(data: dict) -> str:
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _print_diff(old: dict, new: dict) -> None:
    """Print a human-readable summary of what changed between two YAML dicts."""
    changed = False

    for key in ("subheader", "summary"):
        if old.get(key) != new.get(key):
            print(f"  CHANGED {key}:")
            print(f"    old: {str(old.get(key, ''))[:120]!r}")
            print(f"    new: {str(new.get(key, ''))[:120]!r}")
            changed = True

    for key in ("core_competencies", "technical_proficiencies"):
        if old.get(key) != new.get(key):
            print(f"  CHANGED {key}")
            changed = True

    old_bullets = old.get("bullets", {})
    new_bullets = new.get("bullets", {})
    for company in ("truecar", "ekn", "pfizer", "tanabe"):
        ob = old_bullets.get(company, [])
        nb = new_bullets.get(company, [])
        if ob != nb:
            added   = [b for b in nb if b not in ob]
            removed = [b for b in ob if b not in nb]
            print(f"  CHANGED bullets.{company}:")
            for b in removed:
                print(f"    - {b[:100]!r}")
            for b in added:
                print(f"    + {b[:100]!r}")
            changed = True

    if not changed:
        print("  (no changes detected)")


def apply_update(user_request: str, config: dict) -> dict:
    """
    Send the current resume.yaml + user_request to Claude API.
    Returns the updated data dict. Saves it to yaml_working path.

    Args:
        user_request: Natural language description of the change(s) to make.
        config: Loaded layout_config.json dict.

    Returns:
        Updated resume data dict.
    """
    base_dir   = config["paths"]["base_dir"]
    yaml_path  = os.path.join(base_dir, config["paths"]["yaml_working"])
    model      = "claude-opus-4-6"

    current_data = load_yaml(yaml_path)
    current_yaml_str = _yaml_to_str(current_data)

    client = anthropic.Anthropic()
    print(f"Sending request to {model}...")

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": _build_user_message(current_yaml_str, user_request),
            }
        ],
    )

    raw_response = message.content[0].text.strip()

    # Strip accidental markdown code fences if Claude adds them
    if raw_response.startswith("```"):
        lines = raw_response.splitlines()
        raw_response = "\n".join(
            line for line in lines if not line.startswith("```")
        )

    updated_data = yaml.safe_load(raw_response)
    if updated_data is None:
        raise ValueError("Claude returned empty or unparseable YAML")

    validate_yaml(updated_data)

    print("\nChanges:")
    _print_diff(current_data, updated_data)

    save_yaml(yaml_path, updated_data)
    print(f"\nSaved: {yaml_path}")

    return updated_data
