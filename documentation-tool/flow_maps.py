"""Source-backed scenarios showing existing calls, processes, and event handoffs.

These curated diagrams describe representative paths. They are not instrumented
traces, configured build graphs, or claims that every branch executes in a run.
"""
from __future__ import annotations

from source_anchors import make_source_ref


def make_flow_maps(files: list[dict]) -> list[dict]:
    ref = make_source_ref(files)

    def node(id, role, title, summary, action, why, column, row, refs=(), **extra):
        references = list(refs)
        primary = references[0] if references else {}
        return dict(id=id, role=role, title=title, summary=summary, action=action,
                    why=why, column=column, row=row, references=references,
                    path=primary.get('path'), line=primary.get('line'),
                    file_id=primary.get('file_id'), symbol_id=primary.get('symbol_id'),
                    snippet=primary.get('snippet', ''),
                    status='missing' if not references or any(r['status'] == 'missing' for r in references) else 'verified',
                    optional=False, **extra)

    def edge(a, b, label, kind='call'):
        return {'from': a, 'to': b, 'label': label, 'kind': kind}

    def finish(id, title, question, summary, meaning, nodes, edges):
        return dict(id=id, kind='execution', title=title, question=question,
                    summary=summary, edge_meaning=meaning, nodes=nodes, edges=edges)

    from workflow_flows import make_workflow_flows
    from runtime_flows import make_runtime_flows
    maps = [*make_workflow_flows(ref, node, edge, finish),
            *make_runtime_flows(ref, node, edge, finish)]
    if len({item['id'] for item in maps}) != len(maps):
        raise ValueError('Duplicate execution scenario ID')
    for item in maps:
        ids = {step['id'] for step in item['nodes']}
        if len(ids) != len(item['nodes']):
            raise ValueError('Duplicate step in execution scenario ' + item['id'])
        if any(e['from'] not in ids or e['to'] not in ids for e in item['edges']):
            raise ValueError('Unknown step in execution scenario ' + item['id'])
        if any(e['kind'] not in {'call', 'process', 'conditional', 'return', 'event', 'step'} for e in item['edges']):
            raise ValueError('Unknown execution edge type in ' + item['id'])
    return maps
