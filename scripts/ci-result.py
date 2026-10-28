#!/usr/bin/env python3
"""Fail closed unless every required CI job succeeded."""
import json
import os
import sys

REQUIRED = {'governance', 'lint', 'offline'}


def failures(needs):
    if not isinstance(needs, dict):
        return ['CI_NEEDS must be an object']
    return [f'{name}: expected success, got {needs.get(name, {})}'
            for name in sorted(REQUIRED)
            if not isinstance(needs.get(name), dict)
            or needs[name].get('result') != 'success']


def main():
    try:
        needs = json.loads(os.environ['CI_NEEDS'])
        errors = failures(needs)
    except (KeyError, ValueError) as exc:
        print(f'Invalid CI results: {exc}', file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print('All required CI jobs succeeded.')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
