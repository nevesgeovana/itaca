"""Accessor registration (REQ-106): the sanctioned extension point.

``itc.register_accessor(name)`` is a class decorator that registers a
named accessor namespace on VarFrame. After registration, ``db.<name>``
instantiates the accessor class with the frame and caches it per
instance (the xarray pattern). Registering a name that collides with an
existing attribute or another accessor raises at registration time. An
``AttributeError`` escaping the accessor's ``__init__`` is re-raised as
``RuntimeError`` carrying the original, so the attribute machinery never
swallows a real defect silently.

External packages (for example pyflightstream's exporter, DD-23) attach
solver-run views this way without ITACA importing the driver. The
registry supports snapshot and restore for tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from itaca.core.errors import AccessorRegistrationError
from itaca.core.varframe import VarFrame

_T = TypeVar("_T", bound=type)

# name -> accessor class. Registration also sets a descriptor of the
# same name on the VarFrame class, so this dict and the class attributes
# stay in lockstep (snapshot/restore keeps them consistent).
_REGISTERED: dict[str, type] = {}

_CACHE_ATTR = "_accessor_cache"


class _CachedAccessor:
    """Descriptor instantiating and caching an accessor per frame."""

    def __init__(self, name: str, accessor: type) -> None:
        self._name = name
        self._accessor = accessor

    def __get__(self, obj: VarFrame | None, objtype: type | None = None) -> Any:
        if obj is None:
            return self._accessor
        cache = obj.__dict__.get(_CACHE_ATTR)
        if cache is None:
            cache = {}
            object.__setattr__(obj, _CACHE_ATTR, cache)
        if self._name not in cache:
            try:
                cache[self._name] = self._accessor(obj)
            except AttributeError as error:
                # A real defect in the accessor must not be masked by the
                # attribute lookup machinery as "attribute not found".
                raise RuntimeError(
                    f"initializing the '{self._name}' accessor raised "
                    f"AttributeError: {error}"
                ) from error
        return cache[self._name]


def register_accessor(name: str) -> Callable[[_T], _T]:
    """Register a named accessor namespace on VarFrame (REQ-106).

    Parameters
    ----------
    name : str
        The accessor namespace, exposed as ``db.<name>``. It must not
        collide with an existing VarFrame attribute or another
        registered accessor.

    Returns
    -------
    callable
        The class decorator; it returns the accessor class unchanged.

    Raises
    ------
    AccessorRegistrationError
        The name collides with an existing attribute or accessor.

    Examples
    --------
    >>> import numpy as np
    >>> import itaca as itc
    >>> @itc.register_accessor("demo_accessor")
    ... class Demo:
    ...     def __init__(self, db):
    ...         self._db = db
    ...     def n_dims(self):
    ...         return len(self._db.dims)
    >>> arr = np.column_stack([[0.0, 1.0], [1.0, 2.0]])
    >>> db = itc.load(arr, names=["a", "CT"]).pivot(dims=["a"])
    >>> db.demo_accessor.n_dims()
    1
    >>> from itaca.core import accessors
    >>> accessors.restore({})  # tidy up the demo registration
    """

    def decorator(accessor: _T) -> _T:
        if not name.isidentifier():
            raise AccessorRegistrationError(
                f"accessor '{name}'",
                "the name is not a valid Python identifier, so db.<name> "
                "could never reach it",
                "use an identifier name (letters, digits, underscore, not "
                "starting with a digit) (REQ-106)",
            )
        if name in _REGISTERED:
            raise AccessorRegistrationError(
                f"accessor '{name}'",
                "a name already registered as an accessor cannot be registered again",
                f"the holder is {_REGISTERED[name].__name__}; choose "
                "another name (REQ-106)",
            )
        if hasattr(VarFrame, name):
            holder = type(getattr(VarFrame, name, None)).__name__
            raise AccessorRegistrationError(
                f"accessor '{name}'",
                "the name collides with an existing VarFrame attribute",
                f"the holder is a {holder}; choose a name free of the "
                "VarFrame surface (REQ-106)",
            )
        setattr(VarFrame, name, _CachedAccessor(name, accessor))
        _REGISTERED[name] = accessor
        return accessor

    return decorator


def snapshot() -> dict[str, type]:
    """Capture the current accessor registry (for tests)."""
    return dict(_REGISTERED)


def restore(state: dict[str, type]) -> None:
    """Restore the accessor registry to a snapshot (for tests).

    Removes accessors registered after the snapshot and re-adds any
    that were dropped, keeping the VarFrame class attributes in step.
    """
    for name in list(_REGISTERED):
        if name not in state:
            delattr(VarFrame, name)
            del _REGISTERED[name]
    for name, accessor in state.items():
        if name not in _REGISTERED:
            setattr(VarFrame, name, _CachedAccessor(name, accessor))
            _REGISTERED[name] = accessor
