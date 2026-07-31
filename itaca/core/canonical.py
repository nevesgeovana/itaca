r"""Canonical, unambiguous framing for every digest ITACA computes.

REQ-103 and REQ-15. A digest is only as good as the encoding it reads,
and this module owns that encoding so the state hash and the source hash
cannot disagree about it.

The framing is **length-prefixed**, not separator-delimited. Every field
is written as its byte length, an ASCII colon, then its bytes; an absent
field is written as a single ``-``. A length declared BEFORE its content
cannot be forged by content, and ``-`` is not ``0:``, so an absent field
and an empty one are different tokens.

The separator form this replaces had both failures at once (FND-036): it
wrote ``(comment or "")``, so a missing comment and an empty one
collapsed to one digest, and it wrote a bare ``0x1f`` between fields, so
``("op1\x1fx", "y")`` and ``("op1", "x\x1fy")`` collided by carrying
the separator inside the content.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

ABSENT = b"-"
"""The token for a field that is not set, distinct from an empty one."""


def frame(value: bytes | None) -> bytes:
    """Return the canonical framing of one field.

    Parameters
    ----------
    value : bytes or None
        The field content, or ``None`` for an absent field.

    Returns
    -------
    bytes
        ``b"-"`` for an absent field, otherwise the decimal byte length,
        ``b":"``, and the content.

    Examples
    --------
    >>> frame(b"ab")
    b'2:ab'
    >>> frame(b"")
    b'0:'
    >>> frame(None)
    b'-'
    """
    if value is None:
        return ABSENT
    return f"{len(value)}:".encode() + value


def feed(digest: Any, *values: bytes | None) -> None:
    """Write framed fields into a hash object, in order.

    Parameters
    ----------
    digest : hashlib hash object
        The digest to update.
    *values : bytes or None
        Fields to emit, each framed independently.

    Returns
    -------
    None
        The digest is updated in place.

    Examples
    --------
    >>> import hashlib
    >>> d = hashlib.sha256()
    >>> feed(d, b"op", None)
    >>> len(d.hexdigest())
    64
    """
    for value in values:
        digest.update(frame(value))


def text(value: str | None) -> bytes | None:
    """Encode an optional string as an optional field.

    Parameters
    ----------
    value : str or None
        The string to encode.

    Returns
    -------
    bytes or None
        UTF-8 bytes, or ``None``, which frames as absent rather than as
        empty.

    Examples
    --------
    >>> text("deg")
    b'deg'
    >>> text(None) is None
    True
    """
    return None if value is None else value.encode("utf-8")


def feed_array(digest: Any, array: NDArray[Any]) -> None:
    """Emit an array as dtype, shape and contents, each framed.

    Byte order is normalized to NATIVE and memory layout to C order.
    Neither is observable through the read-only public surface
    (REQ-102), so a big-endian and a little-endian array holding the
    same values are the same semantic state and must not hash
    differently. Normalizing to native keeps the digest
    platform-dependent, which REQ-103 already concedes by promising
    equality only on the same platform.

    Parameters
    ----------
    digest : hashlib hash object
        The digest to update.
    array : numpy.ndarray
        The array to emit.

    Returns
    -------
    None
        The digest is updated in place.

    Examples
    --------
    >>> import hashlib
    >>> import numpy as np
    >>> d = hashlib.sha256()
    >>> feed_array(d, np.array([1.0]))
    >>> len(d.hexdigest())
    64
    """
    contiguous = np.ascontiguousarray(array)
    if contiguous.dtype.byteorder not in ("=", "|"):
        contiguous = contiguous.astype(contiguous.dtype.newbyteorder("="))
    feed(
        digest,
        str(contiguous.dtype).encode(),
        str(contiguous.shape).encode(),
        contiguous.tobytes(),
    )
