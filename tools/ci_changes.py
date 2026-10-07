#!/usr/bin/env python3
"""Conservative local-Git selection for development feedback, never qualification."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

# Reviewed narrative documents and the isolated optional editor may omit
# application work. Shared helpers, application runtime and unknown paths stay full.
DOCUMENTS = frozenset({
    'README.md', 'AGENTS.md', 'COMPILE', 'RELEASE',
    'docs/README.md', 'docs/architecture.md', 'docs/ci.md',
    'docs/development-speed.md', 'docs/testing.md', 'docs/validation.md',
    'docs/documentation.md', 'docs/maintenance.md',
    'docs/agent-coordination.md', 'docs/agent-recipes.md', 'docs/agent-lifecycle.md',
})
COMMIT = re.compile(r'[0-9a-f]{40}')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_capacity
# Domains cover dependencies expressed through command lines, generated recipes,
# fixtures and retained inputs, in addition to the source-reference closure below.
TOOL_DOMAINS = (
    frozenset('agent_board agent_edit agent_migrate agent_publish agent_record agent_session agent_stress check_agent_record'.split()),
    frozenset('apt_repo artifact certification distribution_release distro_channel distro_check distro_client github_release latest_release legacy_artifacts package_notices portability release release_check verify_abi verify_legacy_preservation'.split()),
    frozenset('dependencies dependency_archive prepare_dependencies sdk sdk_paths sdk_retention windows_compiler windows_graphics'.split()),
    frozenset('gui_boundary gui_source_group gui_visual gallery_browser screenshots package_wasm rev_probe host_contracts'.split()),
    frozenset('build build_capacity ci_plan ci_changes coverage qualification_tasks run_tests source_identity test_plan'.split()),
    frozenset('ci_apt ci_artifacts ci_cleanup ci_cleanup_repository ci_cleanup_previous ci_cleanup_drafts ci_cleanup_expired ci_retry ci_transport container_job workflow_storage'.split()),
    frozenset('rust_sdk rust_build rust_component rust_workflow build ci_plan source_identity test_plan release release_check offline_acceptance container_job'.split()),
)


def repository_path(path):
    """Only canonical relative Git paths can authorize an omission."""
    return (isinstance(path, str) and bool(path) and '\\' not in path and
            not re.match(r'[A-Za-z]:', path) and
            not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in path) and
            all(part not in ('', '.', '..') for part in path.split('/')))


def editor_path(path):
    """Editor sources and local checks are outside the application graph."""
    return repository_path(path) and (path == 'COMPILE-editor' or path.startswith('editor/'))


def infrastructure_suites(paths, root=ROOT):
    """Select whole suites; unknown/deleted infrastructure requires every suite.

    Source references deliberately overapproximate Python imports: literal dynamic
    loader names and subprocess script names count too. Domain edges include
    non-Python coupling. Missing inventories or unreadable sources fail selection,
    never silently remove a suite from feedback.
    """
    suites = {p.stem[5:]: p for p in (root / 'tests').glob('test_*.py')}
    modules = {p.stem: p for p in (root / 'tools').glob('*.py')}
    if not suites or not modules:
        raise ValueError('complete tooling source and suite inventory required')
    all_suites = sorted(suites)
    if not paths:
        return all_suites
    changed, direct = set(), set()
    for path in paths:
        if not repository_path(path):
            return all_suites
        if path in DOCUMENTS or editor_path(path):
            continue
        if path.startswith('tools/') and Path(path).suffix == '.py' and path.count('/') == 1:
            name = Path(path).stem
            if name not in modules or not any(name in domain for domain in TOOL_DOMAINS):
                return all_suites
            changed.add(name)
        elif path.startswith('tests/test_') and Path(path).suffix == '.py' and path.count('/') == 1:
            name = Path(path).stem[5:]
            if name not in suites:
                return all_suites
            direct.add(name)
            changed.add(name)
        elif path.startswith('gui/'):
            changed.update(TOOL_DOMAINS[3])
        elif path.startswith(('rust/', 'third_party/rust/')):
            changed.update(TOOL_DOMAINS[6])
        elif path.startswith(('src/', 'include/', 'tests/')) and Path(path).suffix in ('.cpp', '.hpp', '.h', '.c', '.cc'):
            continue  # Native application contracts remain in focused/shared-gui jobs.
        else:
            return all_suites
    if not changed:
        return sorted(direct)
    def referenced(file):
        result = set()
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                result.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.add(node.module.split('.')[0])
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Exact literal dynamic-loader names and script paths count;
                # explanatory prose and selector tables do not create edges.
                if re.fullmatch(r'[a-z][a-z0-9_]*', node.value):
                    result.add(node.value)
                result.update(re.findall(r'(?<![A-Za-z0-9_])([a-z][a-z0-9_]*)\.py(?:$|[^A-Za-z0-9_])', node.value))
        return result | {name.removeprefix('test_') for name in result if name.startswith('test_')}
    references = {name: referenced(file) for name, file in modules.items()}
    tests = {name: referenced(file) for name, file in suites.items()}
    initial = set(changed)
    for domain in TOOL_DOMAINS:
        if domain & initial:
            changed.update(domain)
    previous = None
    while previous != changed:
        previous = set(changed)
        changed.update(name for name, dependencies in references.items() if dependencies & changed)
        changed.update(name for name, dependencies in tests.items() if dependencies & changed)
    return sorted(direct | (changed & suites.keys()) |
                  {name for name, dependencies in tests.items() if dependencies & changed})


def load_supervisor():
    spec = importlib.util.spec_from_file_location('feedback_process_tree', ROOT / 'tools/process_tree.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tool_jobs(value):
    if value == 'auto':
        return value
    if value == '':
        raise argparse.ArgumentTypeError('test jobs must be auto or a positive integer')
    try:
        return build_capacity.test_jobs(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def run_tool_suites(suites, output, jobs=None, root=ROOT):
    """Bounded parallel whole-suite execution with the qualification runner policy."""
    if not suites or len(set(suites)) != len(suites):
        raise ValueError('nonempty unique suites required')
    jobs = build_capacity.test_jobs(jobs if jobs is not None else os.environ.get('CTEST_PARALLEL_LEVEL'))
    known = {p.stem[5:] for p in (root / 'tests').glob('test_*.py')}
    if not set(suites) <= known:
        raise ValueError('unknown tooling suite')
    workers = min(jobs, len(suites))
    environment = build_capacity.worker_environment(os.environ, workers, capacity=jobs)
    output.mkdir(parents=True, exist_ok=False)
    processes = load_supervisor()
    def execute(name):
        receipt = output / (name + '.json')
        with (output / (name + '.log')).open('wb') as log:
            owner = processes.launch([sys.executable, '-B', str(root / 'tools/run_tests.py'),
                                      '--suite', name, '--output', str(receipt)], root, log, env=environment)
            try:
                owner.wait(timeout=900)
                code = owner.finish()
            except (subprocess.TimeoutExpired, processes.ProcessTreeError) as error:
                code = 1
                log.write(('\nSuite process ownership failed: ' + str(error) + '\n').encode())
            finally:
                owner.close()  # Join descendants before reading logs or publishing receipts.
        # run_tests rejects skips, expected failures, empty/duplicate inventories
        # and unrecorded cases. Never substitute unittest's weaker exit policy.
        passed = code == 0 and receipt.is_file()
        if passed:
            try:
                passed = json.loads(receipt.read_text())['status'] == 'passed'
            except (ValueError, KeyError):
                passed = False
        print(name + ': ' + ('passed' if passed else 'FAILED'), flush=True)
        if not passed:
            print((output / (name + '.log')).read_text(errors='replace'), flush=True)
        return {'suite': name, 'status': 'passed' if passed else 'failed'}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(execute, suites))
    summary = {'schema_version': 1, 'scope': 'development-feedback', 'suites': results,
               'status': 'passed' if all(r['status'] == 'passed' for r in results) else 'failed'}
    (output / 'summary.json').write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n')
    return summary


def classify(paths):
    """An absent/incomplete change inventory never authorizes omitted work."""
    paths = list(paths)
    canonical = bool(paths) and all(repository_path(path) for path in paths)
    docs_only = canonical and all(path in DOCUMENTS for path in paths)
    editor_only = canonical and all(path in DOCUMENTS or editor_path(path) for path in paths)
    scope = 'documents' if docs_only else 'editor' if editor_only else 'full'
    reason = {'documents': 'Only reviewed narrative documents changed.',
              'editor': 'Only isolated optional editor paths and reviewed narrative documents changed.',
              'full': 'Source, policy, unknown paths or an empty change set require full feedback.'}
    return {'schema_version': 1, 'scope': scope,
            'build': scope == 'full', 'gui': scope == 'full', 'workflow_lint': scope == 'full',
            'changed_paths': paths, 'tool_suites': infrastructure_suites(paths),
            'reason': reason[scope]}


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20).stdout


def commit(value):
    if not isinstance(value, str) or not COMMIT.fullmatch(value) or value == '0' * 40:
        raise ValueError('an exact nonzero commit is required')
    return value


def changed_paths(root, event_name, event, expected_head):
    """Compare the tested merge/tree with its exact event baseline, without APIs.

    Depth-two checkouts contain a PR merge's first parent. A multi-commit push
    may lack its previous tip; that condition deliberately selects full work.
    --no-renames makes moves include both deleted and added paths.
    """
    head = commit(expected_head)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != head:
        raise ValueError('checked-out source differs from the event commit')
    if event_name == 'pull_request':
        base = commit(event['pull_request']['base']['sha'])
        if git(root, 'rev-parse', 'HEAD^1').decode().strip() != base:
            raise ValueError('the tested PR merge does not have the event base parent')
        commit(event['pull_request']['head']['sha'])
        if git(root, 'rev-parse', 'HEAD^2').decode().strip() != event['pull_request']['head']['sha']:
            raise ValueError('the tested PR merge does not have the event head parent')
    elif event_name == 'push':
        base = commit(event['before'])
        if commit(event['after']) != head or event.get('deleted'):
            raise ValueError('push event does not identify the checked-out live tip')
    else:
        raise ValueError('unsupported feedback event')
    raw = git(root, 'diff', '--name-only', '--no-renames', '-z', base, head, '--')
    if raw and not raw.endswith(b'\0'):
        raise ValueError('incomplete changed-path output')
    if not raw:
        return []
    items = raw[:-1].split(b'\0')
    if not all(items):
        raise ValueError('empty changed-path record')
    return [item.decode('utf-8', errors='strict') for item in items]


def select(root, event_name, event, expected_head):
    try:
        return classify(changed_paths(root, event_name, event, expected_head))
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
        result = classify([])
        result['reason'] = 'Complete change inventory unavailable; full feedback selected (' + type(error).__name__ + ').'
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--event', type=Path, default=os.environ.get('GITHUB_EVENT_PATH'))
    parser.add_argument('--event-name', default=os.environ.get('GITHUB_EVENT_NAME', ''))
    parser.add_argument('--head', default=os.environ.get('GITHUB_SHA', ''))
    parser.add_argument('--github-output', type=Path, default=os.environ.get('GITHUB_OUTPUT'))
    parser.add_argument('--summary', type=Path, default=os.environ.get('GITHUB_STEP_SUMMARY'))
    parser.add_argument('--run-tool-suites', action='store_true')
    parser.add_argument('--tool-output', type=Path, default=Path('build/changed-tools'))
    parser.add_argument('--tool-jobs', type=tool_jobs,
                        help='auto or a positive worker count; default is resource-aware')
    args = parser.parse_args(argv)
    try:
        event = json.loads(args.event.read_text(encoding='utf-8')) if args.event else {}
    except (OSError, ValueError):
        event = {}
    result = select(args.root, args.event_name, event, args.head)
    if args.github_output:
        with args.github_output.open('a', encoding='utf-8') as stream:
            for key in ('build', 'gui', 'workflow_lint'):
                stream.write(f'{key}={str(result[key]).lower()}\n')
            stream.write('tools=' + str(bool(result['tool_suites'])).lower() + '\n')
            stream.write('scope=' + result['scope'] + '\n')
    if args.summary:
        with args.summary.open('a', encoding='utf-8') as stream:
            stream.write('Development feedback: ' + result['scope'] + '. ' + result['reason'] + '\n')
            if result['scope'] == 'documents':
                stream.write('Documentation checks run; compile, GUI and workflow syntax work omitted.\n')
            elif result['scope'] == 'editor':
                stream.write('Documentation checks run; application compile, GUI, workflow syntax and tooling suites omitted. Editor checks remain explicit and local.\n')
            stream.write('This selection does not qualify a candidate or release.\n')
    print(json.dumps(result, sort_keys=True))
    if args.run_tool_suites and result['tool_suites']:
        return 0 if run_tool_suites(result['tool_suites'], args.tool_output.resolve(), args.tool_jobs)['status'] == 'passed' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
