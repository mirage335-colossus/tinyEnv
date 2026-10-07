#!/usr/bin/env python3
"""Validate local Markdown destinations, required repository files and JSON."""
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".git", ".agent-work", "build", ".cache", "__pycache__"}
errors = []


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def headings(path):
    identifiers, seen = set(), {}
    content = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", content, re.M):
        anchor = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = seen.get(anchor, 0)
        seen[anchor] = count + 1
        identifiers.add(anchor + ("-" + str(count) if count else ""))
    identifiers.update(re.findall(r'(?:id|name)="([^"]+)"', content))
    return identifiers
required = ["README.md", "AGENTS.md", "COMPILE", "RELEASE", "LICENSE",
            "docs/README.md", "third_party/README.md", "CMakePresets.json"]
for name in required:
    if not (ROOT / name).is_file():
        errors.append("missing required file: " + name)
def repository_files():
    # Prune generated SDK/build trees before traversal: rejecting their files
    # afterward still walks millions of unrelated retained compiler inputs.
    for directory, children, files in os.walk(ROOT, followlinks=False):
        children[:] = [name for name in children if name not in EXCLUDE]
        for name in files:
            yield Path(directory) / name


for path in repository_files():
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDE for part in relative.parts) or not path.is_file():
        continue
    if path.suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, UnicodeError) as error:
            errors.append(f"{relative}: {error}")
    if path.suffix != ".md":
        continue
    # Ignore code fences; template paths inside prose still need real destinations.
    content = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
        target = target.strip().split(" ", 1)[0].strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if destination != ROOT and ROOT not in destination.parents:
            errors.append(f"{relative}: link escapes repository {target}")
        if not destination.exists():
            errors.append(f"{relative}: missing link {target}")
        elif parsed.fragment and destination.suffix == ".md" and unquote(parsed.fragment) not in headings(destination):
            errors.append(f"{relative}: missing heading {target}")

try:
    mapping = json.loads((ROOT / "docs/practice-map.json").read_text(encoding="utf-8"), object_pairs_hook=unique)
    seen = set()
    if mapping["schema_version"] != 1 or not mapping["practices"]:
        raise ValueError("empty or unsupported practice map")
    for entry in mapping["practices"]:
        if set(entry) != {"id", "requirement", "documents", "implementation", "checks"} or entry["id"] in seen:
            raise ValueError("invalid or duplicate practice entry")
        seen.add(entry["id"])
        for field in ("documents", "implementation", "checks"):
            if not entry[field] or len(entry[field]) != len(set(entry[field])):
                raise ValueError("empty or duplicate practice references")
            for name in entry[field]:
                destination = (ROOT / name).resolve()
                if ROOT not in destination.parents or not destination.exists():
                    raise ValueError("missing or unsafe practice reference: " + name)
except (OSError, ValueError, KeyError, TypeError) as error:
    errors.append("practice map: " + str(error))
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Repository documentation links, headings, JSON and practice references are valid")
