#!/usr/bin/env python3
"""File-based qualification tasks for a prepared workspace on any CI runner.

The scheduler selects the actual host and supplies trusted inputs. This module
neither downloads release assets nor publishes or authenticates a CI producer.
"""
import argparse
import json
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import ci_plan
import coverage as evidence


def load_plan(root):
    root = Path(root).resolve(strict=True)
    plan = evidence.load(root / 'build/check-plan.json')
    evidence.validate(plan)
    return root, plan


def executions(root):
    """Return host requirements; scheduling and runner names belong to the CI."""
    _, plan = load_plan(root)
    return dict(plan=plan['id'], mode=plan['mode'], executions=[
        dict(id=item['id'], target=item['target'], environment=item['environment'],
             scope=item['scope'], backends=[row['backend'] for row in evidence.execution_members(plan, item)],
             checks=[row['id'] for row in evidence.execution_members(plan, item)],
             reports=[evidence.result_path(plan, row['id'], 'build/evidence').as_posix()
                      for row in evidence.execution_members(plan, item)])
        for item in evidence.executions(plan)])


def _execution(root, check_id, run_id, attempt):
    if not isinstance(run_id, str) or not evidence.NAME.fullmatch(run_id) or type(attempt) is not int or attempt < 1:
        raise ValueError('explicit run ID and positive attempt required')
    root, plan = load_plan(root)
    matches = [item for item in evidence.executions(plan) if item['id'] == check_id]
    if len(matches) != 1:
        raise ValueError('only a frozen physical execution leader can launch')
    evidence.check_inputs(plan, root, check_ids=[check_id])
    return root, plan, matches[0]


def _needs_browser(item):
    return ci_plan.platform.system() == 'Linux' and ci_plan.needs_browser_prerequisite(item['backend'], item['scope'])


def prepare(root, check_id, run_id, attempt):
    """Explicit prerequisite stage; existing disposable-host guards still apply."""
    root, plan, item = _execution(root, check_id, run_id, attempt)
    result = dict(plan=plan['id'], check=check_id, run_id=run_id, attempt=attempt)
    if not _needs_browser(item):
        return dict(result, status='not_required')
    directory = root / 'build/prerequisites' / check_id
    receipt = ci_plan.install_browser_prerequisite(item['target'], item['environment'], item['backend'], directory)
    receipt.update(result)
    directory.mkdir(parents=True, exist_ok=True)
    evidence.write_new(directory / 'browser.json', receipt)
    return dict(result, status='prepared', receipt=str(directory / 'browser.json'))


def run(root, check_id, run_id, attempt):
    """Run one physical execution, retaining every existing logical receipt."""
    root, plan, item = _execution(root, check_id, run_id, attempt)
    if _needs_browser(item) and not (root / 'build/prerequisites' / check_id / 'browser.json').is_file():
        raise ValueError('run explicit browser prerequisite setup before unprivileged qualification')
    return evidence.run_execution(plan, check_id, root, root / 'build/evidence' / check_id, run_id, attempt)



def adopt(root, run_id, attempt, reports, output):
    """Create an immutable explicit selection of trusted earlier receipts."""
    root, plan = load_plan(root)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('adoption must name a new immutable output')
    result = evidence.adopt(plan, reports, root, run_id, attempt)
    evidence.write_new(output, result)
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for name in ('plan', 'list', 'prepare', 'run', 'adopt'):
        command = commands.add_parser(name)
        command.add_argument('--root', type=Path, default=Path.cwd())
        if name == 'plan':
            command.add_argument('--profile', required=True)
            command.add_argument('--policy', type=Path)
        if name in ('prepare', 'run'):
            command.add_argument('--check', required=True)
        if name in ('prepare', 'run', 'adopt'):
            command.add_argument('--run-id', required=True)
            command.add_argument('--attempt', type=int, required=True)
        if name == 'adopt':
            command.add_argument('--output', type=Path, required=True)
            command.add_argument('reports', type=Path, nargs='+')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'plan':
            import qualification_plan
            root = args.root.resolve(strict=True)
            policy = evidence.load(args.policy) if args.policy else None
            qualification_plan.create_plan(root, root / 'build/candidate', args.profile,
                                           root / 'build/check-plan.json', policy)
            result = executions(root)
        elif args.operation == 'adopt':
            result = adopt(args.root, args.run_id, args.attempt, args.reports, args.output)
        elif args.operation == 'list':
            result = executions(args.root)
        else:
            result = globals()[args.operation](args.root, args.check, args.run_id, args.attempt)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps(dict(status='failed', operation=args.operation, error=str(error))), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1 if args.operation == 'run' and result['status'] != 'passed' else 0


if __name__ == '__main__':
    sys.exit(main())
