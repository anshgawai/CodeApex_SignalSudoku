"""Minimal test runner (no pytest required) for environments without PyPI access."""
from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def load_module(path: Path):
    name = path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_module(path: Path) -> tuple[int, int, list[str]]:
    mod = load_module(path)
    passed = failed = 0
    errors: list[str] = []
    for name in sorted(dir(mod)):
        if not name.startswith('test_'):
            continue
        fn = getattr(mod, name)
        if not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f'  PASS  {path.name}::{name}')
        except Exception as exc:
            failed += 1
            err = f'{path.name}::{name}: {exc}'
            errors.append(err)
            print(f'  FAIL  {err}')
            traceback.print_exc()
    return passed, failed, errors


def main() -> int:
    # Ensure sample workbooks exist when possible.
    sample = ROOT / 'sample_data' / 'sample_io_mdb_clean.xlsx'
    if not sample.exists():
        create = ROOT / 'sample_data' / 'create_sample_data.py'
        if create.exists():
            print('Generating sample data...')
            mod = load_module(create)
            if hasattr(mod, 'main'):
                mod.main()

    test_files = sorted((ROOT / 'tests').glob('test_*.py'))
    total_pass = total_fail = 0
    all_errors: list[str] = []
    for path in test_files:
        print(f'\n=== {path.name} ===')
        p, f, errs = run_module(path)
        total_pass += p
        total_fail += f
        all_errors.extend(errs)

    print(f'\n{total_pass} passed, {total_fail} failed')
    for e in all_errors:
        print(' -', e)
    return 1 if total_fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
