#!/usr/bin/env python3
"""Execute a frozen check inventory and retain exact, bounded, immutable evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import subprocess
import sys
import shlex
import time
import xml.etree.ElementTree as ET

SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
STATUSES = {"passed", "failed", "incomplete", "skipped", "not_run"}
MAX_LOG = 64 * 1024 * 1024


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field: " + key)
        value[key] = item
    return value


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("expected bounded regular JSON file")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def write_new(path, value):
    """A receipt never overwrites an earlier attempt; caller owns the parent."""
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("expected portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("unsafe relative path")
    if any(ord(c) < 32 for c in value):
        raise ValueError("control character in path")
    return path


def local(root, name):
    path = root.joinpath(*relative(name).parts)
    current = root
    for part in relative(name).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("links are not evidence inputs")
    return path


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or set(value) - set(required) - set(optional):
        raise ValueError("missing or unknown fields")


def text(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise ValueError("invalid text field")


def validate(plan):
    fields(plan, {"schema_version", "mode", "subject", "inputs", "checks", "id"})
    if plan["schema_version"] != 1 or plan["mode"] not in ("diagnostic", "candidate", "release"):
        raise ValueError("unsupported coverage plan")
    fields(plan["subject"], {"source_sha256", "inventory_sha256", "configuration_sha256"})
    if any(not isinstance(v, str) or not SHA.fullmatch(v) for v in plan["subject"].values()):
        raise ValueError("subject requires exact digests")
    if not isinstance(plan["inputs"], dict):
        raise ValueError("inputs must be a complete declared map")
    for name, value in plan["inputs"].items():
        relative(name)
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError("invalid input digest")
    if not isinstance(plan["checks"], list) or not 1 <= len(plan["checks"]) <= 4096:
        raise ValueError("empty or excessive check inventory")
    seen = set()
    for item in plan["checks"]:
        fields(item, {"id", "scope", "target", "environment", "backend", "required", "argv",
                      "timeout_seconds", "warning_seconds", "expected_tests"}, {"junit", "qualification", "execution", "sdk_payload"})
        for key in ("id", "scope", "target", "environment", "backend"):
            if not isinstance(item[key], str) or not NAME.fullmatch(item[key]):
                raise ValueError("invalid check identity")
        if item["id"] in seen or type(item["required"]) is not bool:
            raise ValueError("duplicate check or invalid requirement")
        seen.add(item["id"])
        if not isinstance(item["argv"], list) or not item["argv"] or len(item["argv"]) > 256:
            raise ValueError("invalid check command")
        for arg in item["argv"]:
            text(arg)
        for key in ("timeout_seconds", "warning_seconds"):
            n = item[key]
            if type(n) not in (int, float) or not math.isfinite(n) or not 0 < n <= 86400:
                raise ValueError("invalid computation allowance")
        if item["warning_seconds"] > item["timeout_seconds"]:
            raise ValueError("warning exceeds hard limit")
        cases = item["expected_tests"]
        if not isinstance(cases, list) or len(cases) != len(set(cases)):
            raise ValueError("duplicate expected test")
        for case in cases:
            text(case)
        if bool(cases) != ("junit" in item):
            raise ValueError("JUnit and exact test inventory must be supplied together")
        if "junit" in item:
            relative(item["junit"])
        if "qualification" in item:
            relative(item["qualification"])
        if "sdk_payload" in item and (item["scope"] != "source" or item["sdk_payload"] not in ("binary", "complete")):
            raise ValueError("invalid source SDK payload selection")
    validate_executions(plan)
    if plan["id"] != digest({k: v for k, v in plan.items() if k != "id"}):
        raise ValueError("coverage plan digest differs")
    return plan



def execution_members(plan, item):
    return [row for row in plan["checks"] if row.get("execution", row["id"]) == item.get("execution", item["id"])]


def validate_executions(plan):
    for item in plan["checks"]:
        if "execution" not in item:
            continue
        members = execution_members(plan, item)
        if (not isinstance(item["execution"], str) or item["execution"] != members[0]["id"] or
                len(members) < 2 or item["scope"] not in ("source", "recovery", "abi") or
                not item["target"].startswith(("linux-", "windows-")) or
                item["scope"] == "abi" and not item["target"].startswith("linux-")):
            raise ValueError("unsupported grouped execution")
        common = ("execution", "target", "environment", "scope", "argv", "timeout_seconds", "warning_seconds", "expected_tests", "sdk_payload")
        if (any(any(row.get(key) != item.get(key) for key in common) for row in members) or
                len({row["backend"] for row in members}) != len(members) or
                len({row.get("qualification") for row in members}) != len(members) or
                any(row.get("qualification") != row["id"] + ".qualification.json" for row in members)):
            raise ValueError("group changes execution inputs or loses logical backend coverage")


def executions(plan):
    validate(plan)
    return [item for item in plan["checks"] if item.get("execution", item["id"]) == item["id"]]


def result_path(plan, check_id, evidence_root):
    matches = [item for item in plan["checks"] if item["id"] == check_id]
    if len(matches) != 1:
        raise ValueError("unknown logical check")
    item = matches[0]
    return Path(evidence_root) / item.get("execution", check_id) / (check_id + ".result.json" if "execution" in item else "result.json")


def execution_identity(plan, item, run_id, attempt, host):
    members = execution_members(plan, item)
    return dict(schema_version=1, plan=plan["id"], subject=plan["subject"],
                execution=item["execution"], checks=[x["id"] for x in members],
                backends=sorted(x["backend"] for x in members), target=item["target"],
                environment=item["environment"], scope=item["scope"], run_id=run_id, attempt=attempt, host=host)


def freeze(spec):
    if "id" in spec:
        raise ValueError("specification must not already be frozen")
    plan = dict(spec)
    plan["id"] = digest(spec)
    return validate(plan)


def check_inputs(plan, root, *, check_ids=None, metadata_only=False):
    """Verify frozen common inputs and exactly the selected physical payloads."""
    selected = None
    if (check_ids is not None or metadata_only) and any(name.startswith('build/candidate/') for name in plan['inputs']):
        validate(plan)
        if plan['mode'] != 'release': raise ValueError('scoped inputs require a frozen release plan')
        import release
        candidate = Path(root) / 'build/candidate'; manifest = release.verify_metadata(candidate)
        if sha(candidate / 'release.json') != plan['subject']['inventory_sha256']:
            raise ValueError('release metadata differs from frozen subject')
        declared = {'build/candidate/' + name: value for name, value in manifest['files'].items()}
        if any(plan['inputs'].get(name) != value for name, value in declared.items()) or (
                {name for name in plan['inputs'] if name.startswith('build/candidate/')} != set(declared) | {'build/candidate/release.json'}):
            raise ValueError('frozen release input inventory differs from complete metadata')
        selected = {'build/candidate/release.json'}
        if check_ids is not None:
            if not check_ids or len(check_ids) != len(set(check_ids)):
                raise ValueError('complete nonempty check selection required')
            matches = [item for item in executions(plan) if item['id'] in check_ids]
            if {item['id'] for item in matches} != set(check_ids): raise ValueError('unknown physical check selection')
            for item in matches:
                selected.update('build/candidate/' + name for name in release.required_files(manifest, item['target'], item['backend'], item['scope'], binary_source=item.get('sdk_payload') == 'binary'))
    for name, expected in plan['inputs'].items():
        if selected is not None and name.startswith('build/candidate/') and name not in selected: continue
        if sha(local(root, name)) != expected:
            raise ValueError('check input changed: ' + name)


def junit(path, expected):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("excessive JUnit output")
    cases = list(ET.parse(path).getroot().iter("testcase"))
    names = [case.get("name") for case in cases]
    if sorted(names) != sorted(expected) or len(set(names)) != len(names):
        raise ValueError("missing, duplicate or unexpected assertions")
    if any(case.get("status", "run") not in ("run", "passed") or
           any(case.find(tag) is not None for tag in ("skipped", "failure", "error")) for case in cases):
        raise ValueError("failed or skipped assertions")


def host_identity():
    result = {"system": platform.system(), "machine": platform.machine(),
              "release": platform.release(), "version": platform.version(),
              "python": platform.python_version(), "distribution": None,
              "runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion")}
    release = Path("/etc/os-release")
    if platform.system() == "Linux" and release.is_file():
        values = {}
        for line in release.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                parsed = shlex.split(value)
                values[key] = parsed[0] if len(parsed) == 1 else ""
        result["distribution"] = values.get("ID", "unknown") + "-" + values.get("VERSION_ID", "unknown")
    return result


def qualification(root, item, plan, host):
    """Bind the authoritative check receipt and all of its retained evidence."""
    receipt = load(local(root, item["qualification"]))
    fields(receipt, {"schema_version", "source_sha256", "inventory_sha256", "target", "backend",
                     "scope", "host", "status", "details", "assertions", "evidence"})
    if (receipt["schema_version"] != 1 or receipt["status"] != "passed" or
            receipt["host"] != host or any(receipt[k] != item[k] for k in ("target", "backend", "scope")) or
            any(receipt[k] != plan["subject"][k] for k in ("source_sha256", "inventory_sha256"))):
        raise ValueError("qualification receipt names a different subject or execution environment")
    assertions = receipt["assertions"]
    if (not isinstance(assertions, list) or not assertions or
            any(not isinstance(x, str) or not NAME.fullmatch(x) for x in assertions) or
            len(assertions) != len(set(assertions)) or not isinstance(receipt["details"], dict)):
        raise ValueError("qualification needs a nonempty executed assertion inventory")
    if not isinstance(receipt["evidence"], dict):
        raise ValueError("qualification evidence must be an exact map")
    for name, value in receipt["evidence"].items():
        if name in ("result.json", "console.log", item["qualification"]) or not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError("invalid qualification evidence")
        if sha(local(root, name)) != value:
            raise ValueError("qualification evidence changed")
    if item["scope"] in ("source", "recovery"):
        details = receipt["details"]
        if not details.get("executed_tests") or "source.junit.xml" not in receipt["evidence"]:
            raise ValueError("source qualification needs retained, nonempty test outcomes")
        junit(local(root, "source.junit.xml"), details["executed_tests"])
        for name in details.get("tool_reports", []):
            if name not in receipt["evidence"]:
                raise ValueError("tool outcomes absent from retained evidence")
            tool_report(load(local(root, name)))
    if "execution" in item:
        actual = receipt["details"].get("execution")
        if not isinstance(actual, dict):
            raise ValueError("grouped qualification lacks complete execution identity")
        expected = execution_identity(plan, item, actual.get("run_id"), actual.get("attempt"), host)
        if actual != expected or not NAME.fullmatch(str(actual["run_id"])) or type(actual["attempt"]) is not int or actual["attempt"] < 1:
            raise ValueError("grouped qualification differs from frozen execution")
        if "execution.json" not in receipt["evidence"] or load(local(root, "execution.json")) != actual:
            raise ValueError("grouped qualification lacks bound shared evidence")
    return receipt


def tool_report(value):
    fields(value, {"schema_version", "system", "status", "inventory", "excluded", "results"})
    names, excluded, results = value["inventory"], value["excluded"], value["results"]
    if (value["schema_version"] != 1 or value["status"] != "passed" or not names or
            len(names) != len(set(names)) or not isinstance(excluded, dict) or not results or
            set(results) & set(excluded) or set(names) != set(results) | set(excluded) or
            any(item.get("status") != "passed" for item in results.values()) or
            any(not isinstance(reason, str) or not reason for reason in excluded.values())):
        raise ValueError("incomplete inner test outcomes")
    return value


def run_case(plan, check_id, root, output, run_id, attempt, *, _physical=False):
    validate(plan)
    if not isinstance(run_id, str) or not NAME.fullmatch(run_id) or type(attempt) is not int or attempt < 1:
        raise ValueError("invalid run identity")
    matches = [x for x in plan["checks"] if x["id"] == check_id]
    if len(matches) != 1:
        raise ValueError("check not in frozen inventory")
    item = matches[0]
    if "execution" in item and not _physical:
        raise ValueError("grouped check requires the physical execution entry point")
    root = root.resolve(strict=True)
    check_inputs(plan, root, **({'check_ids': [check_id]} if plan['mode'] == 'release' else {}))
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    argv = [x.replace("{python}", sys.executable).replace("{root}", str(root))
             .replace("{evidence}", str(output)).replace("{plan_id}", plan["id"])
             .replace("{run_id}", run_id).replace("{attempt}", str(attempt)) for x in item["argv"]]
    # Execution identity belongs to the validated plan and invocation, not to
    # inherited provider variables. Only the supervised child receives it.
    environment = dict(os.environ, FOUNDATION_PLAN_ID=plan["id"], FOUNDATION_CHECK_ID=check_id,
                       FOUNDATION_RUN_ID=run_id, FOUNDATION_RUN_ATTEMPT=str(attempt))
    started = time.monotonic()
    result = {"schema_version": 1, "plan": plan["id"], "subject": plan["subject"], "check": check_id,
              "run_id": run_id, "attempt": attempt, "status": "not_run", "exit_code": None,
              "created_at": datetime.now(timezone.utc).isoformat(), "argv": argv,
              "host": host_identity(),
              "warnings": [], "error": None}
    log = output / "console.log"
    process = None
    owner = None
    tools = str(Path(__file__).resolve().parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from process_tree import launch, ProcessTreeError
    try:
        with log.open("xb") as stream:
            owner = launch(argv, root, stream, env=environment)
            process = owner.process
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > item["timeout_seconds"] or log.stat().st_size > MAX_LOG:
                    owner.terminate()
                    result["status"] = "incomplete"
                    result["error"] = "outer computation or output limit exhausted"
                    break
                time.sleep(0.05)
            result["exit_code"] = owner.wait()
            owner.finish()
            if log.stat().st_size > MAX_LOG or time.monotonic() - started > item["timeout_seconds"]:
                result["status"], result["error"] = "incomplete", "outer computation or output limit exhausted"
        if result["status"] != "incomplete":
            result["status"] = "passed" if result["exit_code"] == 0 else "failed"
        if result["status"] == "passed" and item["expected_tests"]:
            junit(local(output, item["junit"]), item["expected_tests"])
        if result["status"] == "passed" and "qualification" in item:
            qualification(output, item, plan, result["host"])
        check_inputs(plan, root, **({'check_ids': [check_id]} if plan['mode'] == 'release' else {}))
    except (OSError, ValueError, ET.ParseError, ProcessTreeError, subprocess.TimeoutExpired) as error:
        result["status"], result["error"] = "failed", str(error)
    finally:
        if owner:
            try:
                owner.close()
            except (OSError, ProcessTreeError, subprocess.TimeoutExpired) as error:
                result["status"], result["error"] = "failed", "writer cleanup uncertain: " + str(error)
    result["seconds"] = time.monotonic() - started
    if result["status"] == "passed" and result["seconds"] >= item["warning_seconds"]:
        result["warnings"].append("Complete passing check approached its outer computation limit")
    evidence = [log] + ([local(output, item["junit"])] if "junit" in item else [])
    if "qualification" in item:
        receipt = local(output, item["qualification"])
        if receipt.is_file():
            evidence.append(receipt)
            if result["status"] == "passed":
                evidence += [local(output, name) for name in load(receipt)["evidence"]]
    result["evidence"] = {p.relative_to(output).as_posix(): sha(p) for p in evidence if p.is_file()}
    write_new(output / "result.json", result)
    return result



def run_execution(plan, check_id, root, output, run_id, attempt):
    """Execute once, then publish every exact logical projection after writer closure."""
    validate(plan)
    leaders = [x for x in executions(plan) if x["id"] == check_id]
    if len(leaders) != 1:
        raise ValueError("only a frozen physical execution leader can launch")
    leader = leaders[0]
    if "execution" not in leader:
        return run_case(plan, check_id, root, output, run_id, attempt)
    result = run_case(plan, check_id, root, output, run_id, attempt, _physical=True)
    import copy
    for item in execution_members(plan, leader):
        projected = copy.deepcopy(result)
        projected["check"] = item["id"]
        if result["status"] == "passed":
            original = load(local(output, leader["qualification"]))
            receipt = copy.deepcopy(original)
            receipt["backend"] = item["backend"]
            if item != leader:
                write_new(local(output, item["qualification"]), receipt)
            qualification(output, item, plan, result["host"])
            projected["evidence"].pop(leader["qualification"], None)
            projected["evidence"][item["qualification"]] = sha(local(output, item["qualification"]))
        elif item != leader:
            projected["evidence"].pop(leader["qualification"], None)
        write_new(Path(output) / (item["id"] + ".result.json"), projected)
    return result


def _result_snapshot(path):
    """Bind parsed result fields to the same bounded bytes used by adoption."""
    if path.is_symlink() or not path.is_file():
        raise ValueError('expected bounded regular JSON result')
    with path.open('rb') as stream:
        data = stream.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('expected bounded regular JSON result')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=object_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    return value, hashlib.sha256(data).hexdigest()


def _validated_results(plan, paths, *, adoption=None, selection=False):
    validate(plan)
    expected = {x["id"]: x for x in plan["checks"]}
    paths = [Path(path) for path in paths]
    original_hashes, paths_by_id = {}, {}
    reports = {}
    run_ids = set()
    attempts = set()
    for path in paths:
        value, original_hashes[path] = _result_snapshot(path)
        name = value["check"]
        if (value.get("schema_version") != 1 or name not in expected or name in reports or
                value["plan"] != plan["id"] or value["subject"] != plan["subject"] or
                value["status"] not in STATUSES or type(value["attempt"]) is not int or value["attempt"] < 1):
            raise ValueError("duplicate, unknown or stale result")
        expected_evidence = {"console.log"}
        if value["status"] == "passed" and "junit" in expected[name]:
            expected_evidence.add(expected[name]["junit"])
        allowed_evidence = {"console.log", expected[name].get("junit", "")}
        if "qualification" in expected[name]:
            allowed_evidence.add(expected[name]["qualification"])
            if value["status"] == "passed":
                receipt = qualification(Path(path).parent, expected[name], plan, value["host"])
                expected_evidence |= {expected[name]["qualification"], *receipt["evidence"]}
                allowed_evidence |= set(receipt["evidence"])
        if not expected_evidence <= set(value["evidence"]):
            raise ValueError("missing retained evidence")
        if set(value["evidence"]) - allowed_evidence:
            raise ValueError("unexpected evidence inventory")
        for name_, expected_sha in value["evidence"].items():
            if sha(local(Path(path).parent, name_)) != expected_sha:
                raise ValueError("evidence changed")
        if value["status"] == "passed":
            if value["exit_code"] != 0 or value["error"] is not None:
                raise ValueError("inconsistent passing result")
            check = expected[name]
            if check["expected_tests"]:
                junit(local(Path(path).parent, check["junit"]), check["expected_tests"])
        run_ids.add(value["run_id"])
        attempts.add(value["attempt"])
        reports[name] = value
        paths_by_id[name] = path
    if not reports or (not selection and set(reports) != set(expected)):
        raise ValueError("missing results or mixed runs/attempts; omissions need explicit result records")
    if adoption is not None:
        _validate_adoption(plan, adoption)
        selected = adoption['results']
        if not set(selected) <= set(reports):
            raise ValueError('adoption contains unused result selections')
        for name, value in reports.items():
            path = paths_by_id[name]
            prior = selected.get(name)
            if value['run_id'] != adoption['run_id']:
                raise ValueError('adopted result belongs to another run')
            if prior is None:
                if value['attempt'] != adoption['attempt']:
                    raise ValueError('prior result requires an explicit adoption selection')
            elif (value['status'] != 'passed' or value['attempt'] != prior['attempt'] or
                  value['host'] != prior['host'] or original_hashes[path] != prior['sha256']):
                raise ValueError('adopted result identity or bytes changed')
    elif not selection and (len(run_ids) != 1 or len(attempts) != 1):
        raise ValueError("missing results or mixed runs/attempts; omissions need explicit result records")
    for leader in executions(plan):
        if "execution" not in leader:
            continue
        members = execution_members(plan, leader)
        if not any(x['id'] in reports for x in members):
            continue
        if any(x['id'] not in reports for x in members):
            raise ValueError('adoption must select every logical result of a physical execution')
        rows = [reports[x["id"]] for x in members]
        keys = ("run_id", "attempt", "status", "exit_code", "created_at", "argv", "host", "seconds", "warnings", "error")
        if any(any(row[key] != rows[0][key] for key in keys) for row in rows):
            raise ValueError("logical projections refer to different physical executions")
        if rows[0]["status"] == "passed":
            receipts = [qualification(paths_by_id[x["id"]].parent, x, plan, rows[0]["host"]) for x in execution_members(plan, leader)]
            if any(row["details"] != receipts[0]["details"] or row["evidence"] != receipts[0]["evidence"] for row in receipts):
                raise ValueError("grouped backend projections have different evidence")
            identity = receipts[0]["details"]["execution"]
            if (identity["run_id"], identity["attempt"]) != (rows[0]["run_id"], rows[0]["attempt"]):
                raise ValueError("execution evidence belongs to another run or attempt")
    if any(_result_snapshot(path)[1] != original_hashes[path] for path in paths):
        raise ValueError('result changed during validation')
    return reports, {name: (path, original_hashes[path]) for name, path in paths_by_id.items()}


def _validate_adoption(plan, value):
    fields(value, {'schema_version', 'plan', 'subject', 'run_id', 'attempt', 'results', 'id'})
    if (value['schema_version'] != 1 or value['plan'] != plan['id'] or value['subject'] != plan['subject'] or
            not isinstance(value['run_id'], str) or not NAME.fullmatch(value['run_id']) or
            type(value['attempt']) is not int or value['attempt'] < 2 or
            value['id'] != digest({key: item for key, item in value.items() if key != 'id'})):
        raise ValueError('adoption plan, run or digest differs')
    expected = {item['id'] for item in plan['checks']}
    if not isinstance(value['results'], dict) or not value['results'] or not set(value['results']) <= expected:
        raise ValueError('adoption needs explicit known results')
    for item in value['results'].values():
        fields(item, {'sha256', 'attempt', 'host'})
        if (not isinstance(item['sha256'], str) or not SHA.fullmatch(item['sha256']) or
                type(item['attempt']) is not int or not 1 <= item['attempt'] < value['attempt'] or
                not isinstance(item['host'], dict) or not item['host']):
            raise ValueError('adoption needs prior attempt, exact hash and original host')
    return value


def adopt(plan, paths, root, run_id, attempt):
    """Explicitly select unchanged successful prior receipts; never rewrite them.

    The local caller supplies trusted receipts; provider authentication remains
    the scheduler's responsibility. Full input hashes and physical groups remain
    required. The resulting manifest must be published with write_new().
    """
    validate(plan)
    if not isinstance(run_id, str) or not NAME.fullmatch(run_id) or type(attempt) is not int or attempt < 2:
        raise ValueError('adoption needs an explicit run and later positive attempt')
    root = Path(root).resolve(strict=True)
    reports, snapshots = _validated_results(plan, paths, selection=True)
    leaders = sorted({item.get('execution', item['id']) for item in plan['checks'] if item['id'] in reports})
    input_scope = {'check_ids': leaders} if plan['mode'] == 'release' else {}
    check_inputs(plan, root, **input_scope)
    for name, value in reports.items():
        if value['status'] != 'passed' or value['run_id'] != run_id or not 1 <= value['attempt'] < attempt:
            raise ValueError('only successful earlier attempts from the same run can be adopted')
        check_host(plan, name, value, snapshots[name][0].parent)
    check_inputs(plan, root, **input_scope)
    if any(_result_snapshot(path)[1] != hashed for path, hashed in snapshots.values()):
        raise ValueError('result changed during adoption')
    value = dict(schema_version=1, plan=plan['id'], subject=plan['subject'], run_id=run_id, attempt=attempt,
                 results={name: dict(sha256=snapshots[name][1], attempt=row['attempt'], host=row['host'])
                          for name, row in reports.items()})
    value['id'] = digest(value)
    return _validate_adoption(plan, value)


def check_host(plan, check_id, report, root):
    """Validate actual retained execution context, including browser evidence."""
    check = next(item for item in plan['checks'] if item['id'] == check_id)
    observed = report['host']
    if check['target'].startswith(('linux-', 'windows-')):
        system, architecture = check['target'].split('-', 1)
        machine = observed['machine'].lower()
        machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
        if observed['system'].lower() != system or machine != architecture:
            raise ValueError('actual execution host differs from declared target')
        if check['environment'].startswith(('debian-', 'ubuntu-')) and observed.get('distribution') != check['environment']:
            raise ValueError('actual user-space environment differs from required baseline')
        if check['environment'] == 'windows-2022' and observed.get('runner_image') != 'win22':
            raise ValueError('Windows runner image evidence missing or mismatched')
    if check['environment'] in ('firefox', 'chromium') and report['status'] == 'passed':
        receipt = load(local(root, check['qualification']))
        browser = receipt['details'].get('browser', {})
        if (browser.get('engine') != check['environment'] or not browser.get('browser_version') or browser.get('status') != 'passed'):
            raise ValueError('actual browser evidence missing or differs from required engine')


def merge(plan, paths, *, adoption=None):
    reports, _ = _validated_results(plan, paths, adoption=adoption)
    expected = {x['id']: x for x in plan['checks']}
    run_ids = {row['run_id'] for row in reports.values()}
    required_ok = all(reports[name]["status"] == "passed" for name, x in expected.items() if x["required"])
    return {"schema_version": 1, "plan": plan["id"], "subject": plan["subject"], "mode": plan["mode"],
            "status": "passed" if required_ok else "failed", "run_id": next(iter(run_ids)),
            "checks": reports, "omitted": [n for n, x in reports.items() if x["status"] != "passed"],
            **({"adoption": adoption} if adoption is not None else {})}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest="command", required=True)
    f = s.add_parser("freeze")
    f.add_argument("--spec", type=Path, required=True)
    for name in ("run", "merge"):
        sub = s.add_parser(name)
        sub.add_argument("--plan", type=Path, required=True)
        if name == "run":
            sub.add_argument("--check", required=True)
            sub.add_argument("--root", type=Path, required=True)
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--attempt", type=int, default=1)
        else:
            sub.add_argument("--adoption", type=Path)
            sub.add_argument("reports", type=Path, nargs="+")
        sub.add_argument("--output", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "freeze":
        write_new(a.output, freeze(load(a.spec)))
        return 0
    plan = validate(load(a.plan))
    if a.command == "run":
        result = run_execution(plan, a.check, a.root, a.output, a.run_id, a.attempt)
    else:
        result = merge(plan, a.reports, adoption=load(a.adoption) if a.adoption else None)
        write_new(a.output, result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("coverage: " + str(error), file=sys.stderr)
        sys.exit(1)
