"""Only SystemClock may read the system time (AGENTS.md, section 5.2, rule 4)."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "insumap"
SYSTEM_CLOCK_MODULE = SOURCE_ROOT / "shared" / "time.py"
FORBIDDEN_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "time_ns"),
}


def wall_clock_calls(source: str) -> list[int]:
    """Return the line numbers of calls that read the system time."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        owner_name = (
            owner.id
            if isinstance(owner, ast.Name)
            else owner.attr
            if isinstance(owner, ast.Attribute)
            else None
        )
        if (owner_name, node.func.attr) in FORBIDDEN_CALLS:
            lines.append(node.lineno)
    return lines


def test_detector_finds_every_forbidden_call() -> None:
    source = "\n".join(
        [
            "datetime.now(UTC)",
            "datetime.datetime.utcnow()",
            "date.today()",
            "time.time()",
            "clock.now()",
        ]
    )

    assert wall_clock_calls(source) == [1, 2, 3, 4]


def test_only_system_clock_reads_the_system_time() -> None:
    offenders = {
        str(path.relative_to(SOURCE_ROOT)): lines
        for path in SOURCE_ROOT.rglob("*.py")
        if path != SYSTEM_CLOCK_MODULE
        and (lines := wall_clock_calls(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}


def test_system_clock_module_is_where_the_time_is_read() -> None:
    assert wall_clock_calls(SYSTEM_CLOCK_MODULE.read_text(encoding="utf-8"))
