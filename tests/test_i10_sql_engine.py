"""I-10: SQL engine must work after aurix_core import (schema load + dispose)."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.live
def test_db_execute_after_aurix_import():
    import aurix_core
    from metadata import fetch_dataframe_readonly

    try:
        fetch_dataframe_readonly("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"live ODBC unavailable: {exc}")

    out = aurix_core.db_execute_query(query="SELECT 1 AS ok", db_name="SQL")
    assert "An error occurred" not in out
    assert "ok" in out


@pytest.mark.xfail(
    reason=(
        "Known Windows ODBC + OpenBLAS limitation (I-10): when `import pandas` "
        "runs BEFORE metadata is imported, numpy's OpenBLAS DLLs are loaded "
        "first and corrupt the ODBC Driver Manager's DLL initialisation state. "
        "Any subsequent pyodbc.connect() returns HY000 regardless of what "
        "metadata.py does (ctypes.windll.LoadLibrary in metadata runs too late). "
        "The production guard (aurix_core.py imports metadata BEFORE pandas) "
        "is verified by test_db_execute_after_aurix_import above. "
        "Third-party callers that import pandas before metadata must call "
        "ctypes.windll.LoadLibrary('msodbcsql18.dll') in their own entry point "
        "before any numpy/pandas import."
    ),
    strict=True,  # must stay xfail; if it ever passes, update the guard docs
)
def test_odbc_pandas_first_xfail_documented(tmp_path):
    """Subprocess: pandas imported FIRST, then metadata, then SELECT 1.

    This is the HOSTILE import order.  It is expected to fail on Windows with
    ODBC Driver 18 + OpenBLAS (strict xfail — see reason string above).
    The production import order (metadata before pandas) is tested separately.
    """
    root = str(pathlib.Path(__file__).resolve().parents[1])

    script = textwrap.dedent("""\
        # -*- coding: utf-8 -*-
        import sys
        sys.path.insert(0, sys.argv[1])
        # Hostile order: pandas (OpenBLAS) loads before metadata/pyodbc.
        import pandas as pd  # noqa: F401
        from metadata import fetch_dataframe_readonly
        df = fetch_dataframe_readonly("SELECT 1 AS ok")
        assert not df.empty and int(df.iloc[0, 0]) == 1
        print("PASS")
    """)
    probe = tmp_path / "probe_pandas_first.py"
    probe.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(probe), root],
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0 and "HY000" not in stderr and "ODBC" not in stderr:
        # Unexpected failure (not the ODBC DLL issue) — surface it.
        pytest.fail(
            f"Unexpected subprocess failure (rc={result.returncode}).\n"
            f"stdout: {stdout}\nstderr: {stderr[-600:]}"
        )

    # For the xfail to trigger correctly, assert the expected failure.
    assert result.returncode == 0 and stdout == "PASS"


def test_odbc_metadata_first_safe_import(tmp_path):
    """Subprocess: metadata imported FIRST (production order), then pandas.

    Proves the guard in metadata.py works for the actual production import
    order used by aurix_core.py (metadata -> pandas).  Must always PASS.
    """
    root = str(pathlib.Path(__file__).resolve().parents[1])

    script = textwrap.dedent("""\
        # -*- coding: utf-8 -*-
        import sys
        sys.path.insert(0, sys.argv[1])
        # Production order: metadata (ctypes + pyodbc warm-up) BEFORE pandas.
        from metadata import fetch_dataframe_readonly
        import pandas as pd  # noqa: F401 - loaded after ODBC warm-up
        df = fetch_dataframe_readonly("SELECT 1 AS ok")
        assert not df.empty and int(df.iloc[0, 0]) == 1, (
            "DataFrame empty or wrong value: " + repr(df)
        )
        print("PASS")
    """)
    probe = tmp_path / "probe_metadata_first.py"
    probe.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(probe), root],
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        if "HY000" in stderr or "ODBC" in stderr or "unavailable" in stderr.lower():
            pytest.skip(f"live ODBC unavailable in subprocess: {stderr[-300:]}")
        pytest.fail(
            f"subprocess failed (rc={result.returncode}).\n"
            f"stdout: {stdout}\nstderr: {stderr[-600:]}"
        )

    assert stdout == "PASS", f"Expected 'PASS', got: {stdout!r}\nstderr: {stderr[-300:]}"