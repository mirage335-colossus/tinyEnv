"""Hierarchical, source-literal diagrams for selected critical code paths.

Only captured text is read. Recipes select and connect exact source spans;
neither source nor configuration is executed to create these diagrams.
"""
from __future__ import annotations

from source_anchors import make_source_ref


def make_code_maps(files: list[dict], flow_maps: list[dict]) -> list[dict]:
    records = {file['path']: file for file in files}
    ref = make_source_ref(files)

    def code(id, title, path, start, end=None, *, column=0, row=0,
             role='CODE', emphasis='primary', child=None, note=''):
        anchor = ref(title, path, start)
        node = dict(anchor, id=id, title=title, role=role, column=column, row=row,
                    emphasis=emphasis, code_lines=[], end_line=None, note=note)
        if child:
            node['child'] = dict(child)
        if anchor['status'] == 'verified':
            source = records[path]['text']
            begin = source.index(start)
            stop = begin + len(start)
            if end is not None:
                if source.count(end) != 1 or source.index(end) < begin:
                    node.update(status='missing', note='Source span end changed; review required')
                    return node
                stop = max(stop, source.index(end) + len(end))
            first = source.count('\n', 0, begin) + 1
            last = source.count('\n', 0, max(begin, stop - 1)) + 1
            lines = source.splitlines()
            node.update(line=first, end_line=last,
                        code_lines=[{'line': line, 'text': lines[line - 1]}
                                    for line in range(first, last + 1)])
        return node

    def edge(a, b, label, kind='step', emphasis='primary'):
        return dict(**{'from': a, 'to': b}, label=label, kind=kind, emphasis=emphasis)

    def diagram(id, title, summary, nodes, edges, *, scope='', category='runtime'):
        return dict(id=id, kind='code', title=title, summary=summary, scope=scope,
                    category=category, nodes=nodes, edges=edges, parents=[])

    from runtime_code_maps import make_runtime_code_maps
    from workflow_code_maps import make_workflow_code_maps
    def workflow_diagram(*args, **kwargs):
        kwargs.setdefault('category', 'workflow')
        return diagram(*args, **kwargs)

    parts = [make_workflow_code_maps(code, edge, workflow_diagram),
             make_runtime_code_maps(code, edge, diagram)]
    maps = [m for part in parts for m in part['maps']]
    by_id = {m['id']: m for m in maps}
    if len(by_id) != len(maps):
        raise ValueError('Duplicate detailed code diagram ID')
    kinds = {'call', 'process', 'conditional', 'return', 'event', 'step', 'dependency'}
    for m in maps:
        nodes = m['nodes']
        ids = {n['id'] for n in nodes}
        if not 1 <= len(nodes) <= 6 or len(ids) != len(nodes):
            raise ValueError('Detailed code diagrams require 1-6 unique nodes: ' + m['id'])
        positions = {(n['column'], n['row']) for n in nodes}
        if len(positions) != len(nodes) or any(c not in (0, 1) or r not in (0, 1, 2) for c, r in positions):
            raise ValueError('Detailed code diagram has invalid grid: ' + m['id'])
        if any(e['from'] not in ids or e['to'] not in ids or e['kind'] not in kinds for e in m['edges']):
            raise ValueError('Invalid detailed code edge: ' + m['id'])
        if any(n['emphasis'] not in {'primary', 'supporting'} for n in nodes):
            raise ValueError('Invalid detailed code emphasis: ' + m['id'])

    def attach(child, parent):
        target = by_id.get(child.get('map'))
        if target is None or (child.get('node') and child['node'] not in {n['id'] for n in target['nodes']}):
            raise ValueError('Unresolved detailed diagram child: ' + repr(child))
        if parent not in target['parents']:
            target['parents'].append(parent)

    bindings = {}
    for part in parts:
        if bindings.keys() & part['bindings'].keys():
            raise ValueError('Duplicate overview-to-code binding')
        bindings.update(part['bindings'])
    expected = {m['id'] + '/' + n['id'] for m in flow_maps for n in m['nodes']}
    if set(bindings) != expected:
        raise ValueError('Overview code bindings differ: ' + repr(set(bindings) ^ expected))
    for m in flow_maps:
        for n in m['nodes']:
            n['child'] = dict(bindings[m['id'] + '/' + n['id']])
            attach(n['child'], {'kind': 'flow', 'map': m['id'], 'node': n['id']})
    for m in maps:
        for n in m['nodes']:
            if n.get('child'):
                attach(n['child'], {'kind': 'code', 'map': m['id'], 'node': n['id']})
    # Every detail chart must be reachable from a public scenario overview.
    reached = {child['map'] for child in bindings.values()}
    while True:
        extra = {n['child']['map'] for id in reached for n in by_id[id]['nodes'] if n.get('child')}
        if extra <= reached:
            break
        reached |= extra
    if reached != set(by_id):
        raise ValueError('Unreachable detailed code diagrams: ' + repr(set(by_id) - reached))
    return maps
