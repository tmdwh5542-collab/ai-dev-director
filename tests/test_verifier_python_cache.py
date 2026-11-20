"""Verification must execute edited source even if a snapshot carries a valid-looking old .pyc."""
import os
import py_compile
import sys
from pathlib import Path

import pytest

from core.verifier import Verifier


@pytest.mark.parametrize("expected,passed", [(2, True), (1, False)])
def test_same_size_same_timestamp_edit_cannot_reuse_old_bytecode(tmp_path, expected, passed):
    module = tmp_path / "feature.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    timestamp = 1700000000
    os.utime(module, (timestamp, timestamp))
    cache = Path(py_compile.compile(str(module), doraise=True))
    previous_cache = cache.read_bytes()
    module.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(module, (timestamp, timestamp))

    result = Verifier._execute_cmd([sys.executable, "-c", f"import feature; assert feature.VALUE == {expected}"], tmp_path)

    assert result["executed"] and result["passed"] is passed
    assert module.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert cache.read_bytes() == previous_cache  # no deletion/mutation of the project's old cache
