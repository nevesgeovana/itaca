"""Provenance and operating-mode session state (SRS 4.4.1; REQ-07 to REQ-12).

Provenance is the static, immutable origin record of a VarFrame, set
once at creation and never modified (DD-01). This module also owns the
session-level defaults behind ``itc.set_user`` and ``itc.set_mode``.

Logging here follows the library discipline: module logger, no
handlers, diagnostics only. The durable record is Provenance itself.
"""

from __future__ import annotations

import getpass
import logging
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from itaca.core.errors import ProvenanceError

logger = logging.getLogger(__name__)

VALID_MODES = ("production", "draft")

_session_user: str | None = None
_session_mode: str = "production"


def validate_mode(mode: str) -> None:
    """Raise ``ProvenanceError`` unless ``mode`` is a valid operating mode.

    Parameters
    ----------
    mode : str
        Candidate operating mode.

    Raises
    ------
    ProvenanceError
        If ``mode`` is not ``"production"`` or ``"draft"`` (REQ-08).
    """
    if mode not in VALID_MODES:
        raise ProvenanceError(
            f"operating mode {mode!r}",
            "mode selection with an unknown mode",
            "use 'production' or 'draft' (REQ-08)",
        )


def set_user(name: str | None) -> None:
    """Override the default ``user@hostname`` identity (REQ-07).

    Parameters
    ----------
    name : str or None
        New session user identity. ``None`` restores the default
        derived from ``getpass.getuser()`` and ``socket.gethostname()``.

    Raises
    ------
    ProvenanceError
        If ``name`` is an empty or blank string.

    Examples
    --------
    >>> import itaca as itc
    >>> itc.set_user("geovana@tudelft")
    >>> itc.set_user(None)  # restore the default
    """
    global _session_user
    if name is not None and not name.strip():
        raise ProvenanceError(
            "session user ''",
            "set_user with an empty name",
            "pass a non-empty name, or None to restore the default",
        )
    _session_user = name
    logger.info("session user set to %s", "<default>" if name is None else name)


def set_mode(mode: str) -> None:
    """Set the global default operating mode (REQ-08).

    Parameters
    ----------
    mode : str
        ``"production"`` (default) or ``"draft"``.

    Raises
    ------
    ProvenanceError
        If ``mode`` is not a valid operating mode.

    Examples
    --------
    >>> import itaca as itc
    >>> itc.set_mode("draft")
    >>> itc.set_mode("production")
    """
    global _session_mode
    validate_mode(mode)
    _session_mode = mode
    logger.info("session default mode set to %s", mode)


def current_user() -> str:
    """Return the session user identity (override or ``user@hostname``)."""
    if _session_user is not None:
        return _session_user
    return f"{getpass.getuser()}@{socket.gethostname()}"


def current_mode() -> str:
    """Return the session default operating mode."""
    return _session_mode


@dataclass(frozen=True)
class Provenance:
    """Static, immutable origin record of a VarFrame (SRS 4.4.1).

    ``source_files`` is stored as a tuple, the immutable counterpart of
    the list stated in the SRS table, per structural immutability
    (DD-03).

    Parameters
    ----------
    itaca_version : str
        ITACA version that created the VarFrame.
    user : str
        ``user@hostname``, overridable via ``itc.set_user``.
    created_at : datetime.datetime
        ISO 8601 creation timestamp (timezone-aware).
    source_files : tuple of pathlib.Path
        Paths to the input files.
    source_hash : str
        SHA-256 digest of the concatenated source file contents.
    mode : str
        ``"production"`` or ``"draft"``.
    version_tag : str or None, optional
        User-defined tag, e.g. ``"v1.0-raw"``.
    source_coords : tuple or None, optional
        Per-file dimension coordinates recorded at load time; the
        backing data of ``db.manifest`` (REQ-15). Each entry is
        ``(path_str, ((dim, value_or_star), ...))`` where ``"*"``
        marks a dimension swept within the file.

    Raises
    ------
    ProvenanceError
        If ``mode`` is not a valid operating mode.
    """

    itaca_version: str
    user: str
    created_at: datetime
    source_files: tuple[Path, ...]
    source_hash: str
    mode: str
    version_tag: str | None = None
    source_coords: tuple[tuple[str, tuple[tuple[str, object], ...]], ...] | None = None

    def __post_init__(self) -> None:
        validate_mode(self.mode)
