"""Regression tests for the ERROR/FAIL distinction in the deterministic checkers.

The protocol's own rule is that a missing capability must never be reported as a
negative finding:

    ERROR != NOT_FOUND

Before this fix, ``check_v5_integrity.py`` collapsed a missing PyYAML into a
normal contract FAIL: it emitted "V5 INTEGRITY: FAIL" plus a set of vacuous
"frontmatter missing required key" errors, because it could not parse YAML at
all. Any host whose ``python3`` lacked PyYAML therefore looked like a corrupted
skill. ``liveness_check.sh`` inherited the same collapse at L2.

This was not hypothetical. On a host where the ``python3`` on PATH is a
linuxbrew interpreter without PyYAML, the documented invocation

    AHP_SKILL_DIR="$(pwd)" bash scripts/liveness_check.sh

reported FAIL even though ``python3 scripts/check_v5_integrity.py --root .``
(using an interpreter that does have PyYAML) reported PASS. Running the suite
under a tool that injects PyYAML hid the defect entirely.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = ROOT / "scripts" / "check_v5_integrity.py"
LIVENESS_SCRIPT = ROOT / "scripts" / "liveness_check.sh"


def _load_integrity_module():
    spec = importlib.util.spec_from_file_location("check_v5_integrity_yaml", INTEGRITY_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_missing_pyyaml_is_error_not_fail(monkeypatch, capsys, tmp_path: Path):
    """yaml is None must yield exit 2 (ERROR), never exit 1 (FAIL)."""
    mod = _load_integrity_module()

    # Simulate an environment where PyYAML is not importable.
    monkeypatch.setattr(mod, "yaml", None)
    monkeypatch.setattr(sys, "argv", ["check_v5_integrity.py", "--root", str(ROOT)])

    rc = mod.main()
    captured = capsys.readouterr()

    assert rc == 2, "missing PyYAML must be ERROR (exit 2), not FAIL (exit 1)"
    assert rc != 1
    assert "V5 INTEGRITY: FAIL" not in captured.out
    # It must be explicit about what could not be established.
    assert "PyYAML is unavailable" in captured.err
    assert "not a" in captured.err and "contract violation" in captured.err


def test_missing_pyyaml_does_not_emit_vacuous_missing_key_errors(monkeypatch, capsys):
    """The old behaviour printed 'frontmatter missing required key' for every key.

    Those assertions are meaningless when YAML cannot be parsed, so they must not
    appear as if they were real findings.
    """
    mod = _load_integrity_module()
    monkeypatch.setattr(mod, "yaml", None)
    monkeypatch.setattr(sys, "argv", ["check_v5_integrity.py", "--root", str(ROOT)])

    mod.main()
    captured = capsys.readouterr()

    assert "frontmatter missing required key" not in captured.out


def _run_liveness(skill_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AHP_SKILL_DIR"] = str(skill_dir)
    return subprocess.run(
        ["bash", str(LIVENESS_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_liveness_reports_cannot_run_separately_from_contract_failure(tmp_path: Path):
    """A checker that cannot complete (exit 2) must not read as a contract FAIL."""
    skill = tmp_path / "skill"
    shutil.copytree(ROOT, skill)
    (skill / "scripts" / "check_v5_integrity.py").write_text(
        "#!/usr/bin/env python3\nraise SystemExit(2)\n", encoding="utf-8"
    )

    result = _run_liveness(skill)

    assert result.returncode != 0, "a cannot-run structural check is still a required failure"
    assert "could not complete (ERROR" in result.stdout
    # The specific contract-violation wording must NOT be used here.
    assert "FAILED: the contract was violated" not in result.stdout


def test_liveness_reports_contract_violation_as_fail(tmp_path: Path):
    """A checker that completes and reports a violation (exit 1) is a real FAIL."""
    skill = tmp_path / "skill"
    shutil.copytree(ROOT, skill)
    (skill / "scripts" / "check_v5_integrity.py").write_text(
        "#!/usr/bin/env python3\nraise SystemExit(1)\n", encoding="utf-8"
    )

    result = _run_liveness(skill)

    assert result.returncode != 0
    assert "FAILED: the contract was violated" in result.stdout
    assert "could not complete (ERROR" not in result.stdout


def test_liveness_names_the_interpreter_it_used(tmp_path: Path):
    """The chosen interpreter is reported, so a host-specific mismatch is visible."""
    skill = tmp_path / "skill"
    shutil.copytree(ROOT, skill)

    result = _run_liveness(skill)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "integrity checker passed (interpreter:" in result.stdout
