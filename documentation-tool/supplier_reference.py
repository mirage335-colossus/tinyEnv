"""Capture four pinned GUI contract references without restoring a dependency.

Only regular archive members selected below are read into memory. All metadata
and archive reads are bounded; no member is extracted, imported, or executed.
Verification is against the retained records in the current source checkout,
not an independent signature or a validation of every supplier file.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
from typing import Callable, Any


SELECTED_MEMBERS = (
    'upstream/include/gui/geometry.hpp',
    'upstream/include/gui/contract.hpp',
    'upstream/include/gui/presentation.hpp',
    'upstream/examples/application.hpp',
)
GROUP = 'third_party/gui-inputs'
LOCK = 'third_party/gui-boundary.lock.json'
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 4096
_HASH = re.compile(r'[0-9a-f]{64}')


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _LimitedReader:
    """Limit bytes supplied to tarfile, including PAX and sparse metadata."""
    def __init__(self, stream: Any, limit: int):
        self.stream, self.limit, self.total = stream, limit, 0

    def read(self, size: int = -1) -> bytes:
        remaining = self.limit - self.total
        request = remaining + 1 if size < 0 else min(size, remaining + 1)
        data = self.stream.read(request)
        self.total += len(data)
        if self.total > self.limit:
            raise ValueError(f'expanded archive exceeds {self.limit} byte read limit')
        return data


def _checksum_records(text: str) -> dict[str, str]:
    records = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if not match or match.group(2) in records:
            raise ValueError('invalid or duplicate SHA256SUMS record')
        records[match.group(2)] = match.group(1)
    return records


def capture_supplier_references(source: Path, max_file_bytes: int,
                                read_regular: Callable) -> tuple[list[dict], dict, list[str]]:
    """Return verified synthetic file records, provenance, and visible warnings.

    `read_regular` is the generator's race-aware, symlink-refusing file reader.
    A missing or inconsistent group yields no guessed contract references.
    """
    warnings: list[str] = []
    provenance: dict[str, Any] = {
        'name': 'gui-boundary', 'status': 'unavailable', 'archive': GROUP + '/gui-inputs.tar.gz',
        'selected_members': list(SELECTED_MEMBERS), 'captured_members': [], 'inputs': [],
        'verification_scope': 'Selected members checked against current checkout GUI lock, retained manifest, and SHA256SUMS.',
        'limitations': [
            'Only these four contract/example members are captured; this is not a supplier build or complete supplier inventory.',
            'The captured bytes are pinned upstream references. Local integration patches are not applied.',
            'No archive files are restored or executed, and no build output is inspected.',
            'Consistency with checkout pins is checked; no independent signature or whole-supplier validation is claimed.',
        ],
    }

    def read(relative: str, limit: int) -> bytes:
        path = source / relative
        resolved = path.resolve(strict=True)
        if source != resolved and source not in resolved.parents:
            raise ValueError(f'{relative}: resolved path is outside source root')
        raw, _ = read_regular(path, limit)
        provenance['inputs'].append({'path': relative, 'sha256': _sha(raw), 'max_bytes': limit})
        return raw

    def unavailable(reason: str) -> tuple[list, dict, list]:
        provenance['reason'] = reason
        warnings.append('GUI supplier references unavailable: ' + reason)
        return [], provenance, warnings

    try:
        lock_raw = read(LOCK, MAX_METADATA_BYTES)
        manifest_raw = read(GROUP + '/manifest.json', MAX_METADATA_BYTES)
        checksum_raw = read(GROUP + '/SHA256SUMS', 16 * 1024)
        lock, manifest = json.loads(lock_raw), json.loads(manifest_raw)
        checksums = _checksum_records(checksum_raw.decode('ascii'))
        if not isinstance(lock, dict) or not isinstance(manifest, dict):
            raise ValueError('lock and manifest must be JSON objects')
        if lock.get('name') != 'gui-boundary' or lock.get('schema_version') != 1:
            raise ValueError('unsupported GUI lock identity/schema')
        if manifest.get('kind') != 'foundation-gui-inputs' or manifest.get('schema_version') != 1:
            raise ValueError('unsupported GUI input-group identity/schema')
        if not re.fullmatch(r'[0-9a-f]{40}', str(lock.get('revision', ''))):
            raise ValueError('GUI lock has no pinned revision')
        for field in ('revision', 'upstream', 'source_tree'):
            if not lock.get(field) or lock.get(field) != manifest.get(field):
                raise ValueError(f'GUI lock and manifest disagree on {field}')
        manifest_hash = _sha(manifest_raw)
        if checksums.get('manifest.json') != manifest_hash:
            raise ValueError('manifest.json does not match SHA256SUMS')
        inventory, locked_files = manifest.get('files'), lock.get('files')
        if not isinstance(inventory, dict) or not isinstance(locked_files, dict):
            raise ValueError('missing lock/manifest file inventory')
        locked_record = inventory.get('foundation/' + LOCK, {})
        if not isinstance(locked_record, dict) or locked_record.get('sha256') != _sha(lock_raw) or locked_record.get('size') != len(lock_raw):
            raise ValueError('current GUI lock does not match retained manifest pin')
        archive_raw = read(GROUP + '/gui-inputs.tar.gz', MAX_ARCHIVE_BYTES)
        archive_hash = _sha(archive_raw)
        if checksums.get('gui-inputs.tar.gz') != archive_hash or manifest.get('archive_sha256') != archive_hash:
            raise ValueError('GUI archive does not match retained checksum and manifest pins')
        provenance.update(revision=lock['revision'], source_tree=lock['source_tree'],
                          upstream=lock['upstream'], license=lock.get('license'),
                          archive_sha256=archive_hash, manifest_sha256=manifest_hash,
                          lock_sha256=_sha(lock_raw), checksum_sha256=_sha(checksum_raw))

        expected = {}
        for member in SELECTED_MEMBERS:
            relative = member.removeprefix('upstream/')
            record = inventory.get(member)
            pinned_hash = locked_files.get(relative)
            if not isinstance(record, dict) or not isinstance(pinned_hash, str) or not _HASH.fullmatch(pinned_hash):
                warnings.append(f'GUI supplier reference missing from retained pins: {member}')
                continue
            if record.get('sha256') != pinned_hash:
                warnings.append(f'GUI supplier lock/manifest hash mismatch: {member}')
                continue
            size = record.get('size')
            if type(size) is not int or size < 0 or size > max_file_bytes:
                warnings.append(f'GUI supplier reference outside per-file byte limit: {member}')
                continue
            expected[member] = record
        captured: dict[str, bytes] = {}
        seen: set[str] = set()
        # Opening gzip explicitly lets the limit cover every uncompressed tar byte,
        # including extension headers that tarfile consumes before returning a member.
        with gzip.GzipFile(fileobj=io.BytesIO(archive_raw), mode='rb') as expanded:
            with tarfile.open(fileobj=_LimitedReader(expanded, MAX_EXPANDED_BYTES), mode='r|') as archive:
                for count, member in enumerate(archive, 1):
                    if count > MAX_MEMBERS:
                        raise ValueError(f'archive exceeds {MAX_MEMBERS} member limit')
                    if member.size < 0 or member.size > MAX_EXPANDED_BYTES:
                        raise ValueError('archive contains a member outside expansion bounds')
                    if member.name not in SELECTED_MEMBERS:
                        continue
                    if member.name in seen:
                        raise ValueError(f'duplicate selected archive member: {member.name}')
                    seen.add(member.name)
                    record = expected.get(member.name)
                    if record is None:
                        continue
                    if not member.isreg() or member.issparse() or member.size != record['size']:
                        warnings.append(f'GUI supplier reference is not a regular member with pinned size: {member.name}')
                        continue
                    stream = archive.extractfile(member)
                    if stream is None:
                        warnings.append(f'GUI supplier reference could not be read: {member.name}')
                        continue
                    with stream:
                        raw = stream.read(max_file_bytes + 1)
                    if len(raw) != member.size or len(raw) > max_file_bytes or _sha(raw) != record['sha256']:
                        warnings.append(f'GUI supplier reference content does not match retained pin: {member.name}')
                        continue
                    if b'\x00' in raw:
                        warnings.append(f'GUI supplier reference is binary: {member.name}')
                        continue
                    raw.decode('utf-8-sig')
                    captured[member.name] = raw
        for member in expected:
            if member not in seen:
                warnings.append(f'GUI supplier reference missing from retained archive: {member}')
        files = []
        for member in SELECTED_MEMBERS:
            raw = captured.get(member)
            if raw is None:
                continue
            virtual_path = '@gui-boundary/' + member.removeprefix('upstream/')
            text = raw.decode('utf-8-sig')
            files.append({
                'id': 'f-' + _sha(virtual_path.encode())[:20], 'path': virtual_path,
                'category': 'gui', 'language': 'cpp', 'text': text, 'sha256': _sha(raw),
                'line_count': len(text.splitlines()), 'size': len(raw), 'mtime_ns': None,
                'symbols': [], 'imports': [], 'origin': 'supplier-reference',
                'provenance': {'archive': provenance['archive'], 'member': member,
                               'revision': lock['revision'], 'upstream': lock['upstream'],
                               'archive_sha256': archive_hash, 'manifest_sha256': manifest_hash,
                               'lock_sha256': _sha(lock_raw), 'member_sha256': _sha(raw),
                               'patches_applied': False, 'checked_against': provenance['verification_scope']},
            })
        provenance['captured_members'] = list(captured)
        provenance['status'] = 'verified' if len(files) == len(SELECTED_MEMBERS) else 'partial' if files else 'unavailable'
        if not files:
            provenance['reason'] = 'No selected supplier members passed pin, regular-file, and content checks.'
        return files, provenance, warnings
    except (OSError, ValueError, UnicodeError, tarfile.TarError, EOFError) as exc:
        return unavailable(str(exc))


def recheck_supplier_references(source: Path, provenance: dict,
                               read_regular: Callable) -> list[str]:
    changed = []
    for record in provenance.get('inputs', []):
        try:
            raw, _ = read_regular(source / record['path'], record['max_bytes'])
            if _sha(raw) != record['sha256']:
                changed.append(record['path'])
        except (OSError, ValueError):
            changed.append(record['path'])
    return changed
