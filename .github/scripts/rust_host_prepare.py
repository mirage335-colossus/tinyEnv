#!/usr/bin/env python3
"""Explicit pinned Rust preparation for native candidate runners."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ci_plan
import coverage
import rust_sdk


def prepare(target, output):
    ci_plan.assert_host(target)
    if target not in ci_plan.STANDARD:
        raise ValueError('host preparation requires a supported native target')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Rust host preparation output must be new')
    recipe = ROOT / ci_plan.RUST_RECIPES[target]
    identity = rust_sdk.recipe_identity(recipe)
    inputs = output.parent / 'native-rust-inputs'
    group = output.parent / 'native-rust-group'
    rust_sdk.fetch(recipe, inputs, network=True)
    rust_sdk.prepare(recipe, inputs, group)
    rust_sdk.install(group, identity, output, execute=True)
    receipt = {'schema_version': 1, 'target': target, 'recipe': identity,
               'scope': 'explicit-native-host-preparation',
               'files': rust_sdk.verify_group(group, identity)}
    coverage.write_new(output.parent / 'native-rust-preparation.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=tuple(ci_plan.STANDARD), required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/native-rust-sdk')
    args = parser.parse_args(argv)
    prepare(args.target, args.output)


if __name__ == '__main__':
    main()
