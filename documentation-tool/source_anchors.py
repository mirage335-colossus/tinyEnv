"""Resolve curated documentation references against captured text only."""
from __future__ import annotations


def make_source_ref(files: list[dict]):
    records = {file['path']: file for file in files}

    def ref(label: str, path: str, needle: str) -> dict:
        file = records.get(path)
        result = dict(label=label, path=path, line=None, file_id=None,
                      symbol_id=None, snippet='', status='missing')
        if not file or file['text'].count(needle) != 1:
            result['note'] = 'Source anchor changed; review required'
            return result
        line = file['text'].count('\n', 0, file['text'].index(needle)) + 1
        candidates = [symbol for symbol in file['symbols']
                      if symbol['line'] <= line <= symbol['end_line']
                      and symbol['kind'] in {'function', 'method', 'class', 'struct'}]
        symbol = min(candidates, key=lambda s: s['end_line'] - s['line'], default=None)
        lines = file['text'].splitlines()
        start, stop = max(0, line - 2), min(len(lines), line + 6)
        result.update(line=line, file_id=file['id'], symbol_id=symbol['id'] if symbol else None,
                      snippet='\n'.join(f'{n+1:4}  {lines[n]}' for n in range(start, stop)),
                      status='verified')
        return result

    return ref
