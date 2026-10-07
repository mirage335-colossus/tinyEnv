#!/usr/bin/env python3
"""Verify the complete SDK inventory before CMake initializes the compiler."""
import argparse
from pathlib import Path
from sdk_manifest import verify_sdk
from sdk_environment import require_clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--release', action='store_true')
    args = parser.parse_args()
    require_clean()
    print(verify_sdk(args.root, args.release))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError) as error: raise SystemExit(str(error))
