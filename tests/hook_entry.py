"""Parse a pre-commit hook entry into a wrapper and the command it runs.

Shared by ``tests/test_tooling_config.py`` and
``tests/test_prepush_receipt.py``, which both have to answer "what does
this hook ACTUALLY run" about the same string. One implementation rather
than two, because two copies of a parsing rule are two chances to disagree
about the answer.

WHY IT PARSES INSTEAD OF SEARCHING. Both callers used to scan the raw
entry for substrings. A reviewer measured what that admits: the entry

    python .claude/kit/other_wrapper.py --note ".claude/kit/prepush_receipt.py
    guard --label pytest-full" -- pytest

satisfied every substring assertion in both modules while the program
actually executed was ``other_wrapper.py``. So an unreviewed, unpinned
wrapper could stand in front of the blocking suite with every guard green,
which is exactly the defect those assertions were written to stop. The
mention was in the string; the carrier was not.

``shlex.split`` gives the argv a shell would produce, so a quoted argument
is one token and cannot be mistaken for a program name or a separator.
"""

from __future__ import annotations

import shlex
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RECEIPT = _ROOT / ".claude" / "kit" / "prepush_receipt.py"
_PYTHON_NAMES = frozenset({"python", "python3", "py"})


def split_wrapper(entry: str) -> tuple[list[str] | None, list[str]]:
    """Split a hook entry into ``(wrapper argv or None, command argv)``.

    Parameters
    ----------
    entry : str
        The ``entry:`` value of a local pre-commit hook.

    Returns
    -------
    tuple of (list of str or None, list of str)
        The tokens before the first bare ``--`` and the tokens after it.
        When the entry carries no bare ``--`` it is unwrapped, and the
        wrapper is ``None`` with the whole argv as the command.

    Examples
    --------
    >>> split_wrapper("pytest")
    (None, ['pytest'])
    >>> split_wrapper("python r.py guard --label x -- pytest -q")
    (['python', 'r.py', 'guard', '--label', 'x'], ['pytest', '-q'])
    """
    argv = shlex.split(entry)
    if "--" not in argv:
        return None, argv
    cut = argv.index("--")
    return argv[:cut], argv[cut + 1 :]


def marker_expression(argv: list[str]) -> str:
    """The marker selection a pytest argv actually runs under.

    Parameters
    ----------
    argv : list of str
        A pytest command line, from :func:`split_wrapper`.

    Returns
    -------
    str
        The value of the single ``-m`` option.

    Raises
    ------
    AssertionError
        When there is no ``-m``, when one carries no value, or when there
        is MORE THAN ONE. pytest honors the LAST of several, and a reader
        of the config sees the first, so the two disagree exactly where a
        guard built on this would report on a tier the hook does not run.
        The ambiguity is refused rather than resolved, because a config
        with two selections is a mistake whichever one wins.

    Examples
    --------
    >>> marker_expression(["pytest", "-m", "not slow", "-q"])
    'not slow'
    """
    positions = [i for i, token in enumerate(argv) if token == "-m"]
    assert positions, (
        f"the command {argv!r} carries no `-m` selection, so there is no "
        f"expression to measure a tier with. A tier is DEFINED by its "
        f"selection; restore it."
    )
    assert len(positions) == 1, (
        f"the command {argv!r} carries {len(positions)} `-m` options. pytest "
        f"honors the LAST and a reader sees the first, so a guard reading "
        f"this would measure a tier the hook does not run. Write one "
        f"selection, combining the terms with `and` or `or`."
    )
    index = positions[0]
    assert index + 1 < len(argv), (
        f"the command {argv!r} ends with `-m` and no expression after it."
    )
    return argv[index + 1]


def assert_is_the_vendored_receipt(wrapper: list[str]) -> str:
    """Refuse any wrapper that is not the vendored pre-push receipt.

    Positional and resolved, never a substring: the program is a Python
    interpreter, its script argument RESOLVES to the drift-pinned copy at
    ``.claude/kit/prepush_receipt.py``, the subcommand is ``guard``, and a
    non-empty ``--label`` is present. Only that program may stand in front
    of the blocking suite, because only that program is reviewed, pinned
    and known to run the command in every state it cannot recognize.

    Parameters
    ----------
    wrapper : list of str
        The tokens before the bare ``--``, from :func:`split_wrapper`.

    Returns
    -------
    str
        The parsed ``--label`` value. Returned rather than merely checked
        for non-emptiness, because the label is part of the receipt key
        and is the only thing keeping two wrapped commands from
        authorizing each other's skip, so a CALLER has to be able to pin
        WHICH label it is. Checking only that one exists let a rename, or
        a second hook reusing the same label, pass everything.

    Raises
    ------
    AssertionError
        With the object, the operation and the fix, per this repository's
        three-part error rule.
    """
    assert len(wrapper) >= 3, (
        f"the pre-push hook is wrapped by {wrapper!r}, which is too short to "
        f"be the receipt. Expected `python .claude/kit/prepush_receipt.py "
        f"guard --label <name> -- <command>`."
    )
    program = Path(wrapper[0]).name.lower()
    program = program[:-4] if program.endswith(".exe") else program
    assert program in _PYTHON_NAMES, (
        f"the pre-push hook is wrapped by the program {wrapper[0]!r}, not a "
        f"Python interpreter. Only the vendored receipt may wrap the blocking "
        f"suite; any other wrapper is an unreviewed gate in front of it."
    )
    script = (_ROOT / wrapper[1]).resolve()
    assert script == _RECEIPT.resolve(), (
        f"the pre-push hook runs the script {wrapper[1]!r}, which resolves to "
        f"{script} and not to the vendored receipt at {_RECEIPT}. The receipt "
        f"is drift-pinned in tests/test_kit_drift.py; a script beside it is "
        f"not, so it could be anything."
    )
    assert wrapper[2] == "guard", (
        f"the pre-push hook calls the receipt's {wrapper[2]!r} subcommand. "
        f"Only `guard` runs the command; `status` answers and runs NOTHING, "
        f"so the blocking tier would block on nothing."
    )
    # An ALLOWLIST, not a search. The first version of this function asked
    # only whether `--label` was present, and a reviewer measured what that
    # admits: `--repo <elsewhere>` is an option the receipt honors, so the
    # wrapper could prove it is the right program and still gate on another
    # tree entirely, letting a receipt keyed to an unrelated repository
    # authorize the skip. That is round one's own defect surviving its fix,
    # one option over.
    options = wrapper[3:]
    label = None
    index = 0
    while index < len(options):
        name = options[index]
        assert name in ("--label", "--repo"), (
            f"the wrapper {wrapper!r} passes {name!r} to the receipt. Only "
            f"--label and --repo are allowed in front of the blocking suite; "
            f"anything else changes what the guard measures, and an option "
            f"this check does not understand is refused rather than ignored."
        )
        assert index + 1 < len(options), (
            f"the wrapper {wrapper!r} ends with {name!r} and no value, so the "
            f"receipt would refuse the invocation and the tier would not run."
        )
        value = options[index + 1]
        if name == "--label":
            assert value and not value.startswith("-"), (
                f"the wrapper {wrapper!r} has --label with no value, so the "
                f"label is empty and every wrapped command shares one key. "
                f"Give it a name, conventionally the hook id."
            )
            label = value
        else:
            candidate = Path(value)
            resolved = (
                candidate if candidate.is_absolute() else _ROOT / candidate
            ).resolve()
            assert resolved == _ROOT.resolve(), (
                f"the wrapper {wrapper!r} points --repo at {resolved}, which "
                f"is not this repository at {_ROOT}. The receipt would then "
                f"key on another tree, so a run over unrelated content could "
                f"authorize skipping this one's suite. Drop --repo and let it "
                f"resolve the root from the working directory."
            )
        index += 2
    assert label is not None, (
        f"the wrapper {wrapper!r} carries no --label. The label is part of "
        f"the receipt key, and it is what stops two wrapped commands from "
        f"authorizing each other's skip."
    )
    return label
