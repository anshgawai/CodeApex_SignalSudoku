"""Generate sample Excel files for Signal Sudoku demonstration.

Creates four sample workbooks:
  1. sample_io_mdb.xlsx        – ~80 signals with intentional errors
  2. sample_io_mdb_clean.xlsx  – same data without errors
  3. sample_revision_b.xlsx    – revision of clean file (adds, deletes, mods)
  4. sample_overflow.xlsx      – ~400 signals for capacity-failure demo

Run directly:
    python sample_data/create_sample_data.py
"""
from pathlib import Path
from typing import List, Dict, Tuple

import openpyxl
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
HEADERS = ['Tag', 'IO', 'Cable', 'Pair', 'Grp', 'Seg']

# ---------------------------------------------------------------------------
# Signal templates
# ---------------------------------------------------------------------------

def _build_base_signals() -> List[Dict[str, str]]:
    """Return ~80 realistic signals with a mix of types, cables, groups, segs."""

    signals: List[Dict[str, str]] = []
    row_id = 0

    # ----- Group PROC-100 (AI + DI + AO) - Seg A -----
    cable_ai_1 = 'CBL-AI-001'   # 12-pair
    cable_di_1 = 'CBL-DI-001'   # 24-pair
    cable_ao_1 = 'CBL-AO-001'   # 6-pair

    # AI signals – 15 in PROC-100
    ai_tags_100 = [
        ('100-PT-001', 'Pressure Transmitter'),
        ('100-PT-002', 'Pressure Transmitter'),
        ('100-PT-003', 'Pressure Transmitter'),
        ('100-FT-001', 'Flow Transmitter'),
        ('100-FT-002', 'Flow Transmitter'),
        ('100-TT-001', 'Temperature Transmitter'),
        ('100-TT-002', 'Temperature Transmitter'),
        ('100-TT-003', 'Temperature Transmitter'),
        ('100-LT-001', 'Level Transmitter'),
        ('100-LT-002', 'Level Transmitter'),
        ('100-AT-001', 'Analyser Transmitter'),
        ('100-AT-002', 'Analyser Transmitter'),
        ('100-PT-004', 'Pressure Transmitter'),
        ('100-FT-003', 'Flow Transmitter'),
        ('100-TT-004', 'Temperature Transmitter'),
    ]
    for i, (tag, _desc) in enumerate(ai_tags_100, start=1):
        signals.append({
            'Tag': tag, 'IO': 'AI', 'Cable': cable_ai_1,
            'Pair': str(i), 'Grp': 'PROC-100', 'Seg': 'A',
        })

    # DI signals – 12 in PROC-100
    di_tags_100 = [
        '100-ZSH-001', '100-ZSL-001', '100-ZSH-002', '100-ZSL-002',
        '100-PSH-001', '100-PSL-001', '100-PSH-002', '100-PSL-002',
        '100-FSL-001', '100-FSL-002', '100-LSH-001', '100-LSL-001',
    ]
    for i, tag in enumerate(di_tags_100, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DI', 'Cable': cable_di_1,
            'Pair': str(i), 'Grp': 'PROC-100', 'Seg': 'A',
        })

    # AO signals – 5 in PROC-100
    ao_tags_100 = [
        '100-FCV-001', '100-FCV-002', '100-PCV-001', '100-TCV-001', '100-LCV-001',
    ]
    for i, tag in enumerate(ao_tags_100, start=1):
        signals.append({
            'Tag': tag, 'IO': 'AO', 'Cable': cable_ao_1,
            'Pair': str(i), 'Grp': 'PROC-100', 'Seg': 'A',
        })

    # ----- Group PROC-200 (AI + DI + DO) - Seg A -----
    cable_ai_2 = 'CBL-AI-002'   # 12-pair
    cable_di_2 = 'CBL-DI-002'   # 12-pair
    cable_do_1 = 'CBL-DO-001'   # 12-pair

    # AI – 10 in PROC-200
    ai_tags_200 = [
        '200-PT-001', '200-PT-002', '200-FT-001', '200-FT-002',
        '200-TT-001', '200-TT-002', '200-LT-001', '200-LT-002',
        '200-AT-001', '200-PT-003',
    ]
    for i, tag in enumerate(ai_tags_200, start=1):
        signals.append({
            'Tag': tag, 'IO': 'AI', 'Cable': cable_ai_2,
            'Pair': str(i), 'Grp': 'PROC-200', 'Seg': 'A',
        })

    # DI – 5 in PROC-200
    di_tags_200 = [
        '200-ZSH-001', '200-ZSL-001', '200-PSH-001', '200-FSL-001', '200-LSH-001',
    ]
    for i, tag in enumerate(di_tags_200, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DI', 'Cable': cable_di_2,
            'Pair': str(i), 'Grp': 'PROC-200', 'Seg': 'A',
        })

    # DO – 10 in PROC-200
    do_tags_200 = [
        '200-XV-001', '200-XV-002', '200-XV-003', '200-XV-004', '200-XV-005',
        '200-HV-001', '200-HV-002', '200-HV-003', '200-SOL-001', '200-SOL-002',
    ]
    for i, tag in enumerate(do_tags_200, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DO', 'Cable': cable_do_1,
            'Pair': str(i), 'Grp': 'PROC-200', 'Seg': 'A',
        })

    # ----- Group UTIL-300 (DI + DO + AO) - Seg A -----
    cable_di_3 = 'CBL-DI-003'  # 6-pair
    cable_do_2 = 'CBL-DO-002'  # 6-pair
    cable_ao_2 = 'CBL-AO-002'  # 2-pair

    di_tags_300 = ['300-ZSH-001', '300-ZSL-001', '300-PSH-001', '300-PSL-001', '300-FSL-001', '300-TSH-001']
    for i, tag in enumerate(di_tags_300, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DI', 'Cable': cable_di_3,
            'Pair': str(i), 'Grp': 'UTIL-300', 'Seg': 'A',
        })

    do_tags_300 = ['300-XV-001', '300-XV-002', '300-XV-003', '300-HV-001', '300-SOL-001']
    for i, tag in enumerate(do_tags_300, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DO', 'Cable': cable_do_2,
            'Pair': str(i), 'Grp': 'UTIL-300', 'Seg': 'A',
        })

    ao_tags_300 = ['300-FCV-001', '300-TCV-001']
    for i, tag in enumerate(ao_tags_300, start=1):
        signals.append({
            'Tag': tag, 'IO': 'AO', 'Cable': cable_ao_2,
            'Pair': str(i), 'Grp': 'UTIL-300', 'Seg': 'A',
        })

    # ----- Group SAFE-400 (DI + DO) - Seg B (safety) -----
    cable_di_4 = 'CBL-SDI-001'  # 6-pair safety
    cable_do_3 = 'CBL-SDO-001'  # 6-pair safety

    di_tags_400 = ['400-ESD-001', '400-ESD-002', '400-FGD-001', '400-FGD-002']
    for i, tag in enumerate(di_tags_400, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DI', 'Cable': cable_di_4,
            'Pair': str(i), 'Grp': 'SAFE-400', 'Seg': 'B',
        })

    do_tags_400 = ['400-SDV-001', '400-SDV-002', '400-SDV-003', '400-SDV-004', '400-SDV-005']
    for i, tag in enumerate(do_tags_400, start=1):
        signals.append({
            'Tag': tag, 'IO': 'DO', 'Cable': cable_do_3,
            'Pair': str(i), 'Grp': 'SAFE-400', 'Seg': 'B',
        })

    return signals


def _add_intentional_errors(signals: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Append / modify signals to introduce intentional validation errors."""
    out = [dict(s) for s in signals]  # deep-ish copy

    # 1. Row with missing tag
    out.append({
        'Tag': '', 'IO': 'AI', 'Cable': 'CBL-AI-001',
        'Pair': '20', 'Grp': 'PROC-100', 'Seg': 'A',
    })

    # 2. Duplicate tag (reuse first tag)
    out.append({
        'Tag': '100-PT-001', 'IO': 'AI', 'Cable': 'CBL-AI-001',
        'Pair': '21', 'Grp': 'PROC-100', 'Seg': 'A',
    })

    # 3. Invalid IO type
    out.append({
        'Tag': '100-XX-099', 'IO': 'XX', 'Cable': 'CBL-AI-001',
        'Pair': '22', 'Grp': 'PROC-100', 'Seg': 'A',
    })

    # 4. Missing pair number
    out.append({
        'Tag': '200-PT-099', 'IO': 'AI', 'Cable': 'CBL-AI-002',
        'Pair': '', 'Grp': 'PROC-200', 'Seg': 'A',
    })

    return out


def _build_revision_b(signals: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Create 'revision B' of the clean signal list.

    Changes:
    - Delete 3 signals (indices 0, 5, 10)
    - Add 5 new signals
    - Modify IO type for 2 signals
    - Modify cable for 1 signal
    """
    out = [dict(s) for s in signals]

    # Delete 3 signals (remove by index, highest first to avoid shifting)
    for idx in sorted([0, 5, 10], reverse=True):
        if idx < len(out):
            del out[idx]

    # Modify IO type for 2 existing signals
    # Change the first DI to AI  (was 100-ZSH-001)
    for s in out:
        if s['Tag'] == '100-ZSH-001':
            s['IO'] = 'AI'
            break
    # Change first DO to DI (was 200-XV-001)
    for s in out:
        if s['Tag'] == '200-XV-001':
            s['IO'] = 'DI'
            break

    # Modify cable for 1 signal
    for s in out:
        if s['Tag'] == '300-XV-001':
            s['Cable'] = 'CBL-DO-003'
            break

    # Add 5 new signals
    new_signals = [
        {'Tag': '100-PT-010', 'IO': 'AI', 'Cable': 'CBL-AI-001', 'Pair': '16', 'Grp': 'PROC-100', 'Seg': 'A'},
        {'Tag': '100-FT-010', 'IO': 'AI', 'Cable': 'CBL-AI-001', 'Pair': '17', 'Grp': 'PROC-100', 'Seg': 'A'},
        {'Tag': '200-DI-010', 'IO': 'DI', 'Cable': 'CBL-DI-002', 'Pair': '11', 'Grp': 'PROC-200', 'Seg': 'A'},
        {'Tag': '300-DO-010', 'IO': 'DO', 'Cable': 'CBL-DO-002', 'Pair': '6', 'Grp': 'UTIL-300', 'Seg': 'A'},
        {'Tag': '400-ESD-010', 'IO': 'DI', 'Cable': 'CBL-SDI-001', 'Pair': '5', 'Grp': 'SAFE-400', 'Seg': 'B'},
    ]
    out.extend(new_signals)

    return out


def _build_overflow_signals() -> List[Dict[str, str]]:
    """Build ~400 signals that would overflow a single cabinet with defaults."""
    signals: List[Dict[str, str]] = []
    io_types = ['AI', 'AO', 'DI', 'DO']
    cable_idx = 1

    for grp_num in range(1, 11):  # 10 groups
        grp_name = f'GRP-{grp_num:03d}'
        seg = 'A' if grp_num <= 8 else 'B'

        for io_idx, io_type in enumerate(io_types):
            cable_name = f'CBL-{io_type}-{cable_idx:03d}'
            cable_idx += 1
            for pair in range(1, 11):  # 10 signals per io-type per group
                tag = f'{grp_num:03d}-{io_type[0]}T-{pair:03d}'
                if io_type == 'DO':
                    tag = f'{grp_num:03d}-XV-{pair:03d}'
                elif io_type == 'DI':
                    tag = f'{grp_num:03d}-ZS-{pair:03d}'
                elif io_type == 'AO':
                    tag = f'{grp_num:03d}-CV-{pair:03d}'

                signals.append({
                    'Tag': tag, 'IO': io_type, 'Cable': cable_name,
                    'Pair': str(pair), 'Grp': grp_name, 'Seg': seg,
                })

    return signals  # 10 groups × 4 IO types × 10 = 400


# ---------------------------------------------------------------------------
# Workbook writer
# ---------------------------------------------------------------------------

def _write_workbook(filepath: Path, signals: List[Dict[str, str]]) -> None:
    """Write a list of signal dicts to an Excel workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'IO_MDB'

    # Header
    bold_font = Font(bold=True)
    for col_idx, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = bold_font
        cell.alignment = Alignment(horizontal='center')

    # Data
    for row_idx, sig in enumerate(signals, start=2):
        for col_idx, header in enumerate(HEADERS, start=1):
            ws.cell(row=row_idx, column=col_idx, value=sig.get(header, ''))

    # Auto-width
    for col_idx in range(1, len(HEADERS) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(HEADERS[col_idx - 1])
        for row in range(2, len(signals) + 2):
            cell_val = ws.cell(row=row, column=col_idx).value
            if cell_val and len(str(cell_val)) > max_len:
                max_len = len(str(cell_val))
        ws.column_dimensions[col_letter].width = max_len + 3

    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(filepath))
    print(f'  ✓ Created {filepath}  ({len(signals)} signals)')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Generate all sample data files."""
    print('Signal Sudoku – Generating sample data ...\n')

    base_signals = _build_base_signals()

    # 1. sample_io_mdb.xlsx (with errors)
    signals_with_errors = _add_intentional_errors(base_signals)
    _write_workbook(SCRIPT_DIR / 'sample_io_mdb.xlsx', signals_with_errors)

    # 2. sample_io_mdb_clean.xlsx (no errors)
    _write_workbook(SCRIPT_DIR / 'sample_io_mdb_clean.xlsx', base_signals)

    # 3. sample_revision_b.xlsx
    revision_b = _build_revision_b(base_signals)
    _write_workbook(SCRIPT_DIR / 'sample_revision_b.xlsx', revision_b)

    # 4. sample_overflow.xlsx
    overflow = _build_overflow_signals()
    _write_workbook(SCRIPT_DIR / 'sample_overflow.xlsx', overflow)

    print('\nDone. All sample files created in:', SCRIPT_DIR)


if __name__ == '__main__':
    main()
