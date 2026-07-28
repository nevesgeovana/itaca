"""The .itceq parser: sections, cycle detection, opt-in sort (REQ-48, DD-17).

Fixture-based by design: the builtin processors that would exercise the
grammar are M1 stretch scope, so the parser carries its own files
(M1 execution plan, Section 5). Each fixture is written inline so the
grammar under test is visible next to the assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from itaca.core.errors import ItceqCycleError, ItceqParseError
from itaca.pproc.equations.parser import ItceqSpec, parse_itceq

FULL = """\
[meta]
name        = "Aircraft balance campaign: power off"
version     = "1.0"
author      = "Geovana Neves"
description = "6-component internal balance"

[constants]
S_ref = 0.1963
c_ref = 0.2526

[uncertainties]
FZ  = 0.005
rho = "0.05%"

[equations]
q_inf = "0.5 * rho * V**2"
CL    = "FZ / (q_inf * S_ref)"
CM    = "MY / (q_inf * S_ref * c_ref)"

[corrections]
blockage = "1 + 0.005 * CL**2"
CL_corr  = "CL * blockage"
"""


def write(tmp_path: Path, text: str, name: str = "case.itceq") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The five sections
# ---------------------------------------------------------------------------


def test_parses_the_five_sections_in_file_order(tmp_path: Path) -> None:
    spec = parse_itceq(write(tmp_path, FULL))
    assert isinstance(spec, ItceqSpec)
    assert spec.meta["name"] == "Aircraft balance campaign: power off"
    assert spec.meta["version"] == "1.0"
    assert spec.constants == {"S_ref": 0.1963, "c_ref": 0.2526}
    assert spec.uncertainties == {"FZ": 0.005, "rho": "0.05%"}
    assert [eq.target for eq in spec.equations] == ["q_inf", "CL", "CM"]
    assert spec.equations[0].expression == "0.5 * rho * V**2"
    assert [eq.target for eq in spec.corrections] == ["blockage", "CL_corr"]
    assert spec.sorted is False


def test_required_variables_exclude_constants_and_file_targets(tmp_path: Path) -> None:
    # REQ-48: constants are registered before any equation, so they are
    # supplied by the file. What is left is what the VarFrame must carry.
    spec = parse_itceq(write(tmp_path, FULL))
    assert spec.required_variables == ("FZ", "MY", "V", "rho")


def test_optional_sections_default_to_empty(tmp_path: Path) -> None:
    spec = parse_itceq(write(tmp_path, '[meta]\nname = "bare"\n'))
    assert spec.constants == {}
    assert spec.uncertainties == {}
    assert spec.equations == ()
    assert spec.corrections == ()
    assert spec.required_variables == ()


def test_meta_is_required(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError, match="no \\[meta\\] section"):
        parse_itceq(write(tmp_path, '[equations]\nx = "y + 1"\n'))


def test_unknown_section_is_refused(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[equation]\nCL = "FZ"\n'
    with pytest.raises(ItceqParseError, match="unknown section"):
        parse_itceq(write(tmp_path, text))


def test_meta_fields_must_be_strings(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError, match="\\[meta\\] field 'version'"):
        parse_itceq(write(tmp_path, "[meta]\nversion = 1.0\n"))


def test_constants_must_be_numeric(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[constants]\nS_ref = "0.19"\n'
    with pytest.raises(ItceqParseError, match="constant 'S_ref'"):
        parse_itceq(write(tmp_path, text))


def test_boolean_is_not_a_number(tmp_path: Path) -> None:
    # bool is an int in Python; a silently accepted true would become 1.0.
    text = '[meta]\nname = "x"\n\n[constants]\nS_ref = true\n'
    with pytest.raises(ItceqParseError, match="constant 'S_ref'"):
        parse_itceq(write(tmp_path, text))


@pytest.mark.parametrize("value", ['"5"', '"5%%"', '"%"', "true"])
def test_malformed_uncertainty_is_refused(tmp_path: Path, value: str) -> None:
    text = f'[meta]\nname = "x"\n\n[uncertainties]\nFZ = {value}\n'
    with pytest.raises(ItceqParseError, match="uncertainty for 'FZ'"):
        parse_itceq(write(tmp_path, text))


@pytest.mark.parametrize("value", ["0.005", '"0.05%"', '"  2.5 % "', "0"])
def test_wellformed_uncertainty_is_accepted(tmp_path: Path, value: str) -> None:
    text = f'[meta]\nname = "x"\n\n[uncertainties]\nFZ = {value}\n'
    assert "FZ" in parse_itceq(write(tmp_path, text)).uncertainties


def test_equation_target_must_be_an_identifier(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[equations]\n"C L" = "FZ + 1"\n'
    with pytest.raises(ItceqParseError, match="equation target 'C L'"):
        parse_itceq(write(tmp_path, text))


def test_equation_expression_must_be_a_string(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[equations]\nCL = 2.0\n'
    with pytest.raises(ItceqParseError, match="equation 'CL'"):
        parse_itceq(write(tmp_path, text))


def test_equation_syntax_error_is_caught_at_parse_time(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[equations]\nCL = "FZ / ("\n'
    with pytest.raises(ItceqParseError, match="equation 'CL'"):
        parse_itceq(write(tmp_path, text))


def test_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError, match="does not exist"):
        parse_itceq(tmp_path / "absent.itceq")


def test_malformed_toml_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError, match="is not valid TOML"):
        parse_itceq(write(tmp_path, "[meta\nname = "))


def test_a_constant_shadowing_an_equation_target_is_refused(tmp_path: Path) -> None:
    # Measured before the rule existed: k = 2.0 in [constants] with
    # k = "rho * 100.0" in [equations] made x = "k + 1" evaluate to 3.0
    # and History record `x = 2.0 + 1`. The equation ran and its result
    # was unreachable, silently.
    text = (
        '[meta]\nname = "x"\n\n[constants]\nk = 2.0\n\n'
        '[equations]\nk = "rho * 100.0"\nx = "k + 1"\n'
    )
    with pytest.raises(ItceqParseError, match="would never be read"):
        parse_itceq(write(tmp_path, text))


def test_a_constant_shadowing_a_correction_target_is_refused(tmp_path: Path) -> None:
    text = (
        '[meta]\nname = "x"\n\n[constants]\nblockage = 1.02\n\n'
        '[corrections]\nblockage = "1 + CL"\n'
    )
    with pytest.raises(ItceqParseError, match="\\['blockage'\\]"):
        parse_itceq(write(tmp_path, text))


def test_a_correction_replacing_an_equation_target_stays_legal(tmp_path: Path) -> None:
    # The refusal above is about a constant and a target sharing a name,
    # not about redefinition inside the equation sections, which is what
    # SRS Section 4.6 provides for.
    text = (
        '[meta]\nname = "x"\n\n[equations]\nCL = "FZ / q"\n\n'
        '[corrections]\nCL = "CL * 1.02"\n'
    )
    assert parse_itceq(write(tmp_path, text)).targets == ("CL",)


def test_meta_idempotent_is_read_as_a_boolean(tmp_path: Path) -> None:
    # REQ-48 says the file defines the workflow in full, and idempotence
    # decides whether it may legally re-run, so it is declared here.
    text = '[meta]\nname = "x"\nidempotent = true\n'
    spec = parse_itceq(write(tmp_path, text))
    assert spec.idempotent is True
    assert "idempotent" not in spec.meta  # the mapping stays strings-only


def test_meta_idempotent_defaults_to_false(tmp_path: Path) -> None:
    assert parse_itceq(write(tmp_path, '[meta]\nname = "x"\n')).idempotent is False


def test_a_quoted_idempotent_is_refused_rather_than_ignored(tmp_path: Path) -> None:
    # The old strings-only rule accepted "True" and nothing ever read
    # it, so its suggested fix produced a silently ignored field.
    text = '[meta]\nname = "x"\nidempotent = "True"\n'
    with pytest.raises(ItceqParseError, match="unquoted"):
        parse_itceq(write(tmp_path, text))


def test_non_utf8_bytes_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "latin.itceq"
    path.write_bytes(b'[meta]\nname = "caf\xe9"\n')
    with pytest.raises(ItceqParseError, match="not valid UTF-8"):
        parse_itceq(path)


def test_a_section_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError, match="section \\[meta\\]"):
        parse_itceq(write(tmp_path, "meta = 3\n"))


def test_a_cycle_reached_from_outside_reports_the_cycle(tmp_path: Path) -> None:
    # d is not in the cycle but is stuck behind it; the message must
    # still name the cycle, not the first unordered target.
    text = '[meta]\nname = "x"\n\n[equations]\nd = "a"\na = "b"\nb = "a"\n'
    with pytest.raises(ItceqCycleError) as caught:
        parse_itceq(write(tmp_path, text))
    assert "a -> b -> a" in str(caught.value)


def test_duplicate_target_is_refused(tmp_path: Path) -> None:
    # tomllib refuses a duplicate key; the parser reports it as its own.
    text = '[meta]\nname = "x"\n\n[equations]\nCL = "FZ"\nCL = "FX"\n'
    with pytest.raises(ItceqParseError, match="is not valid TOML"):
        parse_itceq(write(tmp_path, text))


# ---------------------------------------------------------------------------
# Cycle detection (REQ-48): at parse time, in either mode (OQ-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("auto_sort", [False, True])
def test_cycle_in_equations_raises_in_either_mode(
    tmp_path: Path, auto_sort: bool
) -> None:
    text = '[meta]\nname = "x"\n\n[equations]\na = "b + 1"\nb = "a + 1"\n'
    with pytest.raises(ItceqCycleError, match="cyclic"):
        parse_itceq(write(tmp_path, text), auto_sort=auto_sort)


def test_cycle_error_names_the_chain(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[equations]\na = "c + 1"\nb = "a"\nc = "b"\n'
    with pytest.raises(ItceqCycleError) as caught:
        parse_itceq(write(tmp_path, text))
    message = str(caught.value)
    assert "a" in message and "b" in message and "c" in message
    assert "->" in message


def test_self_reference_in_equations_is_a_cycle(tmp_path: Path) -> None:
    # [equations] derives new variables; replacement is what [corrections]
    # is for (SRS Section 4.6 section rules).
    text = '[meta]\nname = "x"\n\n[equations]\nCL = "CL * 1.02"\n'
    with pytest.raises(ItceqCycleError, match="cyclic"):
        parse_itceq(write(tmp_path, text))


def test_correction_may_replace_a_variable_the_equations_defined(
    tmp_path: Path,
) -> None:
    # "[corrections] may replace existing variables" (SRS Section 4.6):
    # the right-hand CL is the value [equations] produced, not this entry.
    text = (
        '[meta]\nname = "x"\n\n[equations]\nCL = "FZ / q"\n\n'
        '[corrections]\nblockage = "1 + CL"\nCL = "CL * blockage"\n'
    )
    spec = parse_itceq(write(tmp_path, text))
    assert [eq.target for eq in spec.corrections] == ["blockage", "CL"]


def test_a_correction_may_replace_a_variable_the_frame_supplies(
    tmp_path: Path,
) -> None:
    # SRS Section 4.6: [corrections] "may replace existing variables".
    # Existing includes what the VarFrame carries, which is the ordinary
    # wind tunnel case of correcting a measured channel in place, so the
    # right-hand V is the frame's value and this is not a self-cycle.
    text = '[meta]\nname = "x"\n\n[corrections]\nV = "V * calib"\n'
    spec = parse_itceq(write(tmp_path, text))
    assert [eq.target for eq in spec.corrections] == ["V"]
    # The frame must then supply it, so validate can say so.
    assert spec.required_variables == ("V", "calib")


def test_cycle_within_corrections_raises(tmp_path: Path) -> None:
    text = '[meta]\nname = "x"\n\n[corrections]\na = "b"\nb = "a"\n'
    with pytest.raises(ItceqCycleError, match="cyclic"):
        parse_itceq(write(tmp_path, text))


def test_a_constant_shadowing_a_target_is_not_an_edge(tmp_path: Path) -> None:
    # S_ref is supplied by [constants] before any equation runs, so a
    # reference to it never participates in the dependency graph.
    text = (
        '[meta]\nname = "x"\n\n[constants]\nS_ref = 0.19\n\n'
        '[equations]\nCL = "FZ / S_ref"\n'
    )
    assert parse_itceq(write(tmp_path, text)).required_variables == ("FZ",)


def test_function_names_and_numpy_are_not_dependencies(tmp_path: Path) -> None:
    text = (
        '[meta]\nname = "x"\n\n[equations]\n'
        'theta = "atan2(w, u) + sqrt(pi) * np.sin(u)"\n'
    )
    spec = parse_itceq(write(tmp_path, text))
    assert spec.required_variables == ("u", "w")


# ---------------------------------------------------------------------------
# Ordering (DD-17): file order by default, opt-in topological sort
# ---------------------------------------------------------------------------

UNSORTED = (
    '[meta]\nname = "x"\n\n[equations]\n'
    'CL = "FZ / (q_inf * S)"\nq_inf = "0.5 * rho * V**2"\n'
)


RUNNABLE = (
    '[meta]\nname = "x"\n\n[equations]\n'
    'q_inf = "0.5 * rho * V**2"\nCL = "FZ / (q_inf * S)"\n'
)


def test_file_order_is_the_default(tmp_path: Path) -> None:
    spec = parse_itceq(write(tmp_path, RUNNABLE))
    assert [eq.target for eq in spec.equations] == ["q_inf", "CL"]
    assert spec.sorted is False


def test_a_forward_reference_is_refused_in_file_order(tmp_path: Path) -> None:
    # UNSORTED reads q_inf before defining it. In file order that either
    # raises from compute about a variable the file visibly defines, or
    # silently uses a same-named measured channel that the next line
    # then overwrites. Neither is acceptable, so the file is refused.
    with pytest.raises(ItceqParseError, match="defines below it"):
        parse_itceq(write(tmp_path, UNSORTED))


def test_the_forward_reference_message_names_the_way_out(tmp_path: Path) -> None:
    with pytest.raises(ItceqParseError) as caught:
        parse_itceq(write(tmp_path, UNSORTED))
    message = str(caught.value)
    assert "'CL'" in message and "q_inf" in message
    assert "auto_sort=True" in message


def test_auto_sort_emits_the_earliest_ready_equation_first(tmp_path: Path) -> None:
    # The resolved order is the stable topological order: at every step
    # the earliest equation in FILE order whose dependencies are met.
    # That can hoist an independent equation above a dependent one (zz
    # here), which is harmless and, more to the point, reproducible.
    # DD-17's concern is behavior depending on parser tiebreaking, and
    # this rule is stated rather than incidental. It is deliberately not
    # an edit-distance-minimal reordering, which would be a second rule
    # to specify and to keep stable.
    text = (
        '[meta]\nname = "x"\n\n[equations]\n'
        'CL = "FZ / q"\nzz = "alpha * 2"\nq = "0.5 * rho * V**2"\n'
    )
    spec = parse_itceq(write(tmp_path, text), auto_sort=True)
    assert [eq.target for eq in spec.equations] == ["zz", "q", "CL"]


def test_auto_sort_resolves_the_dependency_order(tmp_path: Path) -> None:
    spec = parse_itceq(write(tmp_path, UNSORTED), auto_sort=True)
    assert [eq.target for eq in spec.equations] == ["q_inf", "CL"]
    assert spec.sorted is True


def test_auto_sort_reports_the_resolved_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # DD-17: the sort is opt-in and reports what it chose, so a file whose
    # behavior depends on it says so out loud.
    parse_itceq(write(tmp_path, UNSORTED), auto_sort=True)
    printed = capsys.readouterr().out
    assert "auto_sort" in printed
    assert "q_inf -> CL" in printed


def test_file_order_prints_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The feedback belongs to the opt-in path only: a default parse is
    # silent, so a library call does not narrate itself.
    parse_itceq(write(tmp_path, RUNNABLE))
    assert capsys.readouterr().out == ""


def test_auto_sort_breaks_ties_by_file_order(tmp_path: Path) -> None:
    # DD-17's stated risk is behavior depending on parser tiebreaking.
    # Independent equations keep their file order, so the resolved order
    # is a minimal, reproducible rearrangement rather than a hash order.
    text = (
        '[meta]\nname = "x"\n\n[equations]\n'
        'z = "a"\ny = "b"\nx = "c"\nw = "z + y + x"\n'
    )
    spec = parse_itceq(write(tmp_path, text), auto_sort=True)
    assert [eq.target for eq in spec.equations] == ["z", "y", "x", "w"]


def test_auto_sort_sorts_corrections_independently_and_after(
    tmp_path: Path,
) -> None:
    text = (
        '[meta]\nname = "x"\n\n[equations]\n'
        'CL = "FZ / q"\nq = "0.5 * rho * V**2"\n\n'
        '[corrections]\nCL_corr = "CL * blockage"\nblockage = "1 + CL"\n'
    )
    spec = parse_itceq(write(tmp_path, text), auto_sort=True)
    assert [eq.target for eq in spec.equations] == ["q", "CL"]
    assert [eq.target for eq in spec.corrections] == ["blockage", "CL_corr"]


def test_spec_is_immutable(tmp_path: Path) -> None:
    spec = parse_itceq(write(tmp_path, FULL))
    with pytest.raises((AttributeError, TypeError)):
        spec.equations = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        spec.constants["S_ref"] = 1.0  # type: ignore[index]
