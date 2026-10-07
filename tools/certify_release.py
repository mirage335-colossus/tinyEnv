#!/usr/bin/env python3
"""Qualify immutable local release bytes against a complete explicit policy."""
import argparse
import importlib.util
from pathlib import Path
import sys


def sibling(name):
    tools = str(Path(__file__).resolve().parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location("foundation_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


coverage = sibling("coverage")


def requirements(policy, profile):
    coverage.fields(policy, {"schema_version", "profiles"})
    if policy["schema_version"] != 1 or profile not in policy["profiles"]:
        raise ValueError("unknown release qualification profile")
    selected = policy["profiles"][profile]
    coverage.fields(selected, {"description", "targets", "checks"})
    if not selected["targets"] or not selected["checks"]:
        raise ValueError("empty release support contract")
    expected = set()
    for target, backends in selected["targets"].items():
        if not coverage.NAME.fullmatch(target) or not backends or len(backends) != len(set(backends)):
            raise ValueError("invalid target/backend contract")
        if any(not coverage.NAME.fullmatch(backend) for backend in backends):
            raise ValueError("invalid backend")
    for row in selected["checks"]:
        coverage.fields(row, {"target", "backend", "environment", "scope"})
        key = tuple(row[k] for k in ("target", "backend", "environment", "scope"))
        if (key in expected or row["target"] not in selected["targets"] or
                row["backend"] not in selected["targets"][row["target"]] or
                any(not isinstance(v, str) or not coverage.NAME.fullmatch(v) for v in row.values())):
            raise ValueError("duplicate or invalid required coverage")
        expected.add(key)
    for target, backends in selected["targets"].items():
        for backend in backends:
            kinds = {r[3] for r in expected if r[:2] == (target, backend)}
            if not {"source", "archive", "recovery"} <= kinds:
                raise ValueError("each delivered backend needs source, archive and recovery coverage")
    return selected, expected


def certify(directory, manifest, plan, reports, policy, profile, experiment=False, *, adoption=None):
    """verify_release must have verified manifest and file bytes before this call."""
    selected, expected = requirements(policy, profile)
    coverage.validate(plan)
    subject = {"source_sha256": manifest["source"]["sha256"],
               "inventory_sha256": coverage.sha(directory / "release.json"),
               "configuration_sha256": coverage.digest({"policy": policy, "profile": profile})}
    if plan["mode"] != "release" or plan["subject"] != subject:
        raise ValueError("diagnostic, different source, inventory or policy cannot certify these bytes")
    actual_targets = {}
    for artifact in manifest["artifacts"]:
        target = artifact["target"]
        actual_targets.setdefault(target, set())
        for backend in artifact["backends"] or ["core"]:
            if backend in actual_targets[target]:
                raise ValueError("duplicate delivered backend")
            actual_targets[target].add(backend)
    if actual_targets != {t: set(b) for t, b in selected["targets"].items()}:
        raise ValueError("delivered target/backend inventory differs from support contract")
    declared = set()
    for check in plan["checks"]:
        key = tuple(check[k] for k in ("target", "backend", "environment", "scope"))
        if key in declared:
            raise ValueError("duplicate qualification scope")
        declared.add(key)
        if key in expected and not check["required"]:
            raise ValueError("mandatory qualification scope marked optional")
        if key in expected and "qualification" not in check:
            raise ValueError("mandatory scope needs a bound qualification receipt")
    if not expected <= declared:
        raise ValueError("required qualification scope missing from plan")
    if not set(manifest["required_scopes"]) <= {r[3] for r in expected}:
        raise ValueError("release requirements absent from qualification policy")
    for leader in coverage.executions(plan):
        if "execution" in leader:
            covered = {x["backend"] for x in coverage.execution_members(plan, leader)}
            if covered != actual_targets[leader["target"]]:
                raise ValueError("grouped execution must cover every delivered backend")
    reports = list(reports)
    package_reports = [path for path in reports if coverage.load(path).get('check') == 'native-packages']
    if len(package_reports) != (1 if 'packages' in manifest else 0):
        raise ValueError('integrated packages require exactly one complete native qualification report')
    application_reports = [path for path in reports if path not in package_reports]
    result = coverage.merge(plan, application_reports, adoption=adoption)
    report_paths = {coverage.load(path)["check"]: path for path in application_reports}
    for check in plan["checks"]:
        coverage.check_host(plan, check['id'], result['checks'][check['id']], report_paths[check['id']].parent)
    native_packages = (sibling('release_package_check').validate_report(package_reports[0], manifest, plan, result)
                       if package_reports else None)
    passed = result["status"] == "passed"
    # Neither an enclosing green workflow nor an advisory warning waives a check.
    warnings = {n: r["warnings"] for n, r in result["checks"].items() if r["warnings"]}
    return {"schema_version": 1, "subject": subject, "profile": profile, "plan": plan["id"],
            "status": ("passed_with_warnings" if warnings else "passed") if passed else "failed",
            "eligible_for_promotion": passed and not experiment, "experiment": experiment,
            "run_id": result["run_id"], "description": selected["description"],
            "warnings": warnings, "omitted": result["omitted"], "coverage": result["checks"],
            "reports": [{"name": str(p.name), "sha256": coverage.sha(p)} for p in reports],
            **({"adoption": result["adoption"]} if adoption is not None else {}),
            **({"native_packages": native_packages} if native_packages is not None else {}),
            "limits": ["Evidence applies only to the named environments and exact bytes.",
                       "Containers do not qualify another kernel, physical device or desktop session.",
                       "This helper neither publishes a release nor changes a remote Latest pointer."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment", action="store_true")
    parser.add_argument("--adoption", type=Path, help="immutable explicit prior-receipt selection")
    parser.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args()
    directory = args.release.resolve(strict=True)
    if directory == args.output.resolve() or directory in args.output.resolve().parents:
        raise ValueError("certification evidence must not mutate the immutable release directory")
    release = sibling("release")
    manifest = release.verify_release(directory)
    initial = coverage.sha(directory / "release.json")
    result = certify(directory, manifest, coverage.load(args.plan), args.reports,
                     coverage.load(args.policy), args.profile, args.experiment,
                     adoption=coverage.load(args.adoption) if args.adoption else None)
    release.verify_release(directory)
    if initial != coverage.sha(directory / "release.json"):
        raise ValueError("release changed during certification")
    coverage.write_new(args.output, result)
    return 0 if result["status"] in ("passed", "passed_with_warnings") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("certification: " + str(error), file=sys.stderr)
        sys.exit(1)
