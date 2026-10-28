#!/usr/bin/env python3
"""Preview or explicitly apply repository bot labels using the existing gh session."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Ben8368/umi-mainline'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create/update labels in this repository')
    args = parser.parse_args()
    labels = json.loads((ROOT / '.github/labels.json').read_text())
    for label in labels:
        if args.apply:
            subprocess.run(['gh', 'label', 'create', label['name'], '--repo', REPOSITORY,
                            '--color', label['color'], '--description', label['description'],
                            '--force'], check=True)
        print(('applied' if args.apply else 'preview') + ': ' + label['name'])
    print('External App installation and default-branch workflow activation are separate checks.')


if __name__ == '__main__':
    main()
