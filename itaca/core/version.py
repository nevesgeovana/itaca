"""Version tagging for ITACA (REQ-92, DD-21).

The version is single-sourced here; ``pyproject.toml`` reads it at
build time via ``tool.setuptools.dynamic``. The value is bumped at
release time, and the release workflow refuses a ``v*`` tag that does
not match it.
"""

__version__ = "0.1.0"
