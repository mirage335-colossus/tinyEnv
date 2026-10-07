#!/usr/bin/env python3
"""Stage an installed package's explicit runtime closure and optional baseline audit."""
import argparse
from pathlib import Path
import sys

from dependency_archive import write_json
from stage_runtime import stage
from verify_abi import audit, elf, inspect, version


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=Path, required=True)
    p.add_argument("--root", type=Path, action="append", default=[])
    p.add_argument("--processor", choices=("x86_64", "aarch64"), required=True)
    p.add_argument("--bookworm", action="store_true")
    p.add_argument("--elf-editor", default="patchelf")
    a = p.parse_args()
    prefix = a.prefix.resolve(strict=True)
    inputs = [path for path in (prefix / "bin").iterdir() if path.is_file() and elf(path)]
    if not inputs:
        raise ValueError("installed package has no native executables")
    stage(inputs, a.root, prefix / "lib/runtime", a.processor, audit_baseline=a.bookworm,
          elf_editor=a.elf_editor)
    ceilings = None
    if not a.bookworm:
        ceilings = {}
        for path in prefix.rglob("*"):
            if path.is_file() and elf(path):
                for family, required in inspect(path)["requirements"].items():
                    if version(required) > version(ceilings.get(family, "0")):
                        ceilings[family] = required
    report = audit(prefix, a.processor, ceilings=ceilings)
    report["baseline_qualification"] = "bookworm-abi-only" if a.bookworm else "native-observed-requirements-only"
    installed_report = prefix / "share/doc/Foundation/runtime-audit.json"
    write_json(installed_report, report)
    installed_report.chmod(0o644)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print("package runtime: " + str(error), file=sys.stderr)
        sys.exit(1)
