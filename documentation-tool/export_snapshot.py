#!/usr/bin/env python3
"""Publish a saved documentation snapshot as a portable, checked-in reader bundle.

Copies the saved HTML/PDFs without rebuilding or executing application code.
The output must be a fresh directory. Replacing an older publication is a
separate, explicit maintainer action.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True

ASSETS = (
    'index.html', 'explorer.js', 'explorer.css',
    'AI-AUTHORED__GUI-MENTAL-MODEL.html',
)
DATA_PREFIX = 'window.DOCMAP_DATA='
READER_PDFS = {
    '00-edit-paths.pdf', '01-code-walkthroughs.pdf', '02-compiler-reference.pdf',
    '03-execution-flows.pdf', '04-code-flowcharts.pdf',
    'AI-AUTHORED__GUI-MENTAL-MODEL.pdf',
}


def read_file(root: Path, relative: str) -> Path:
    """Require a regular, nonsymlink input inside the saved snapshot."""
    path = root / relative
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
        raise ValueError('Snapshot input must not be a symlink: ' + relative)
    if not path.is_file() or root not in path.resolve().parents:
        raise ValueError('Missing regular snapshot input: ' + relative)
    return path


def load_model(snapshot: Path) -> dict:
    if (snapshot / 'atlas.json').exists():
        model = json.loads(read_file(snapshot, 'atlas.json').read_text(encoding='utf-8'))
    else:
        # The reader data is a JSON literal, not executable input to this tool.
        text = read_file(snapshot, 'data.js').read_text(encoding='utf-8').strip()
        if not text.startswith(DATA_PREFIX) or not text.endswith(';'):
            raise ValueError('Expected the saved DOCMAP_DATA JSON assignment')
        model = json.loads(text[len(DATA_PREFIX):-1])
    if not isinstance(model, dict) or model.get('schema_version') != 2:
        raise ValueError('Expected a schema-2 documentation snapshot')
    for field in ('files', 'pdfs', 'conceptual_guide', 'generated_at', 'fingerprint'):
        if field not in model:
            raise ValueError('Snapshot is missing ' + field)
    if not isinstance(model['files'], list) or not isinstance(model['pdfs'], list):
        raise ValueError('Snapshot files and PDFs must be lists')
    if not isinstance(model['conceptual_guide'], dict):
        raise ValueError('Snapshot conceptual guide must be an object')
    if not all(isinstance(model[field], str) for field in ('generated_at', 'fingerprint')):
        raise ValueError('Snapshot capture date and fingerprint must be strings')
    return model


def export_snapshot(snapshot: Path, output: Path) -> None:
    if snapshot.expanduser().is_symlink() or output.expanduser().is_symlink():
        raise ValueError('Snapshot and output directories must not be symlinks')
    snapshot = snapshot.expanduser().resolve()
    output = output.expanduser().resolve()
    if not snapshot.is_dir():
        raise ValueError('Snapshot directory does not exist')
    if output.exists():
        raise ValueError('Output already exists; choose a fresh staging directory')
    if snapshot == output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('Output and input snapshot must be separate directories')

    model = load_model(snapshot)
    original_root = str(model.get('source_root', ''))
    # Source locations throughout the atlas are already repository-relative.
    # Only capture diagnostics may contain the former physical checkout root.
    model['source_root'] = '.'
    if original_root and original_root != '.':
        for skipped in model.get('skipped', []):
            for key in ('path', 'reason'):
                if isinstance(skipped.get(key), str):
                    skipped[key] = skipped[key].replace(original_root, '.')

    def retains_checkout_path(value: object) -> bool:
        if isinstance(value, str):
            return original_root in value
        if isinstance(value, dict):
            return any(retains_checkout_path(v) for v in value.values())
        if isinstance(value, list):
            return any(retains_checkout_path(v) for v in value)
        return False

    # Check decoded values before JSON escaping, including Windows separators.
    if original_root and original_root != '.' and retains_checkout_path(model):
        raise ValueError('Checkout path remains in captured content; review the snapshot before publication')
    serialized = json.dumps(model, ensure_ascii=False, separators=(',', ':'))
    # Identical JSON payloads keep the inventory and offline reader consistent;
    # compact serialization also avoids a second whitespace-heavy inventory.
    serialized = serialized.replace('<', '\\u003c').replace('>', '\\u003e')
    serialized = serialized.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')

    inputs = [(name, read_file(snapshot, name)) for name in ASSETS]
    pdf_names = set()
    for pdf in model['pdfs']:
        if not isinstance(pdf, dict) or not isinstance(pdf.get('title'), str):
            raise ValueError('Each PDF needs a filename and text title')
        name = pdf['name']
        if (not isinstance(name, str) or '/' in name or '\\' in name
                or not name.endswith('.pdf') or name in pdf_names):
            raise ValueError('Invalid or duplicate PDF filename in snapshot')
        # Optional broad inventories print the original source root on covers.
        # Do not publish those unchanged while promising portable metadata.
        if name not in READER_PDFS:
            raise ValueError('Export supports the default reader PDFs; capture without --reference-handbooks')
        pdf_names.add(name)
        relative = 'pdf/' + name
        inputs.append((relative, read_file(snapshot, relative)))

    pdf_links = '\n'.join('- [' + p['title'] + '](pdf/' + p['name'] + ')' for p in model['pdfs'])
    readme = f"""# Included documentation

This is a checked-in, ready-to-read navigation snapshot. Rebuilding is unnecessary
to read it. It is updated only on explicit request and may lag the application.

- [Interactive code and edit-path explorer](index.html)
- [AI-authored conceptual explorer](AI-AUTHORED__GUI-MENTAL-MODEL.html)

Open the HTML files in a browser from a local clone or downloaded copy. GitHub's
file view shows HTML source; the PDFs below can be read directly on GitHub.
Keep this directory together so all diagram, source and PDF links work.

## Printable collection

{pdf_links}

## Snapshot provenance

- Source captured: `{model['generated_at']}`
- Captured source fingerprint: `{model['fingerprint']}`
- AI-authored explanation date: `{model['conceptual_guide'].get('authored_at', 'unknown')}`
- `source_root` is the portable label `.`; captured file paths are repository-relative.
- `atlas.json` and `data.js` contain the same complete captured model. The former
  supports PDF inventory links; the latter lets the explorer work offline.

The AI-authored explanations are saved content; reading, copying and rebuilding
these documents do not call AI. Application code and current source files are
unnecessary for reading this snapshot.

For a requested update, see the [documentation tool](../README.md) and
[conceptual maintainer notes](../AI-AUTHORED__GUI-MENTAL-MODEL-MAINTENANCE.md).
"""
    output.mkdir(parents=True, exist_ok=False)
    for relative, path in inputs:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    (output / 'atlas.json').write_text(serialized + '\n', encoding='utf-8')
    (output / 'data.js').write_text(DATA_PREFIX + serialized + ';\n', encoding='utf-8')
    (output / 'README.md').write_text(readme, encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path,
                        help='Existing saved snapshot to copy; source code is not reread')
    parser.add_argument('--output', required=True, type=Path,
                        help='Fresh reader-bundle directory, such as documentation-tool/published')
    args = parser.parse_args(argv)
    export_snapshot(args.snapshot, args.output)
    print('Published reader bundle: ' + str(args.output))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('export_snapshot: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
