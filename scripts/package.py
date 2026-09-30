#!/usr/bin/env python3
"""Package the committed source tree for a tagged release."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise SystemExit('Commit completed changes before packaging.')
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output.resolve() / f'codex-hub-{version}.tar.gz'
    subprocess.run(['git', 'archive', '--format=tar.gz', f'--prefix=codex-hub-{version}/', '-o', str(archive), 'HEAD'], cwd=ROOT, check=True)
    print(archive)

if __name__ == '__main__':
    main()
