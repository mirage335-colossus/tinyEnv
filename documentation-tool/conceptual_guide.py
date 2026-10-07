"""Load the explicitly AI-authored guide and resolve its local source links.

The explanation is versioned editorial content. Regeneration only checks
anchors and renders it; no model, network request or application code runs.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from source_anchors import make_source_ref


BASENAME = 'AI-AUTHORED__GUI-MENTAL-MODEL'
HTML_NAME = BASENAME + '.html'
PDF_NAME = BASENAME + '.pdf'


def make_conceptual_guide(files: list[dict], code_maps: list[dict]) -> dict:
    guide = json.loads(Path(__file__).with_name(BASENAME + '.json').read_text(encoding='utf-8'))
    ref = make_source_ref(files)
    maps = {m['id']: m for m in code_maps}
    diagrams = guide.get('diagrams', [])
    diagram_ids: set[str] = set()
    warnings: list[str] = []
    source_count = 0
    kinds = {'call', 'data', 'application', 'boundary', 'backend', 'core'}
    edge_kinds = {'call', 'data', 'event', 'return', 'step'}
    if not diagrams:
        raise ValueError('AI-authored conceptual guide has no diagrams')
    for diagram in diagrams:
        id = diagram['id']
        if not re.fullmatch(r'[a-z][a-z0-9-]*', id) or id in diagram_ids:
            raise ValueError('Invalid or duplicate conceptual diagram ID: ' + id)
        diagram_ids.add(id)
        nodes = diagram['nodes']
        ids = {n['id'] for n in nodes}
        if not 1 <= len(nodes) <= 8 or len(ids) != len(nodes):
            raise ValueError('Conceptual diagrams require 1-8 unique nodes: ' + id)
        positions = {(n['column'], n['row']) for n in nodes}
        if len(positions) != len(nodes) or any(
                type(c) is not int or type(r) is not int or not 0 <= c <= 2 or not 0 <= r <= 5
                for c, r in positions):
            raise ValueError('Conceptual diagram has invalid grid: ' + id)
        if any(n['kind'] not in kinds for n in nodes):
            raise ValueError('Invalid conceptual node kind: ' + id)
        for node in nodes:
            detail = node.get('detail')
            if detail:
                target = maps.get(detail.get('map'))
                if target is None or (detail.get('node') and detail['node'] not in {n['id'] for n in target['nodes']}):
                    raise ValueError('Unresolved conceptual detail link: ' + repr(detail))
            source = node.get('source')
            if source:
                source_count += 1
                node['source_ref'] = ref(node['title'], source['path'], source['needle'])
                if node['source_ref']['status'] != 'verified':
                    warnings.append(id + '/' + node['id'] + ': ' + source['path'])
        for edge in diagram['edges']:
            if edge['from'] not in ids or edge['to'] not in ids or edge['kind'] not in edge_kinds:
                raise ValueError('Invalid conceptual diagram edge: ' + id)
    guide.update(html_file=HTML_NAME, pdf_file=PDF_NAME,
                 source_status='review-required' if warnings else 'verified',
                 source_warnings=warnings, source_anchor_count=source_count)
    return guide
