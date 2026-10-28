#!/usr/bin/env bash
# Prepare a lightweight Jules environment; never build or boot umi here.
set -Eeuo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
  echo "Usage: bash scripts/jules-setup.sh [--check]" >&2
  exit 2
fi
if [[ $(uname -s) != Linux ]]; then
  echo "Jules setup requires Linux; use the documented Linux VM, not the macOS host." >&2
  exit 2
fi

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$repo_root"
printf 'OS=%s ARCH=%s BASH=%s\n' "$(uname -s)" "$(uname -m)" "$BASH_VERSION"
for tool in python3 git node shellcheck; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 2; }
done
python3 -c 'import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 2)'
node -e 'console.log(process.version); process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 2)'
git --version
shellcheck --version

if [[ ${1:-} != --check ]]; then
  python3 -m venv .venv/jules
  .venv/jules/bin/python -m pip install --disable-pip-version-check PyYAML==6.0.3
fi
python=.venv/jules/bin/python
if [[ ! -x "$python" ]]; then
  echo "Missing .venv/jules; run setup without --check first." >&2
  exit 2
fi
"$python" -c 'import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 2)'
"$python" -c 'import yaml; assert yaml.__version__ == "6.0.3", yaml.__version__'
"$python" scripts/governance-docs-check.py
"$python" tests/governance-docs.py
"$python" tests/bot-dispatch.py
echo "Jules lightweight setup passed. Activate .venv/jules/bin/activate before task checks."
echo "No Docker daemon, umi, hardware or target-device qualification was performed."
