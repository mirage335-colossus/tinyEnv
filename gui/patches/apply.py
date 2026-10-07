#!/usr/bin/env python3
"""Apply one reviewed unified diff exactly; no search, offsets or fuzzy matching."""
import argparse
from pathlib import Path
import re


def apply(source, patch):
    lines = source.splitlines(keepends=True)
    edits = patch.splitlines(keepends=True)
    if len(edits) < 3 or not edits[0].startswith('--- ') or not edits[1].startswith('+++ '):
        raise ValueError('Expected one unified diff')
    output, cursor, index = [], 0, 2
    while index < len(edits):
        match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n', edits[index])
        if not match:
            raise ValueError('Malformed hunk')
        start, count, target, added = (int(v) if v is not None else 1 for v in match.groups())
        start = start - 1 if start else 0
        if start < cursor or start > len(lines):
            raise ValueError('Out of order hunk')
        output.extend(lines[cursor:start]); cursor = start
        if len(output) != (target - 1 if target else 0):
            raise ValueError('Unexpected target offset')
        index += 1; consumed = produced = 0
        while index < len(edits) and not edits[index].startswith('@@ '):
            line = edits[index]; index += 1
            if line[0] in ' -':
                if cursor >= len(lines) or lines[cursor] != line[1:]:
                    raise ValueError('Patch context differs from verified source')
                cursor += 1; consumed += 1
            if line[0] in ' +':
                output.append(line[1:]); produced += 1
            if line[0] not in ' +-':
                raise ValueError('Invalid patch line')
        if (consumed, produced) != (count, added):
            raise ValueError('Hunk counts differ')
    return ''.join(output + lines[cursor:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('patch', type=Path)
    parser.add_argument('output', type=Path); args = parser.parse_args()
    result = apply(args.source.read_text(), args.patch.read_text())
    if not args.output.exists() or args.output.read_text() != result:
        args.output.write_text(result)
