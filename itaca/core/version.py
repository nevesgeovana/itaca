"""Version tagging for ITACA (REQ-92, DD-21).

The version is single-sourced here; ``pyproject.toml`` reads it at
build time via ``tool.setuptools.dynamic``. M0 ships as ``0.1.0``; the
``dev`` suffix marks the pre-release state and is removed at tag time.
"""

__version__ = "0.1.0"
