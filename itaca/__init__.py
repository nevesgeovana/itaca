"""ITACA: Integrated Toolkit for Aerospace Computation and Analysis.

From data to wisdom. Import convention::

    import itaca as itc
"""

from itaca.core.errors import ITACAError
from itaca.core.provenance import set_mode, set_user
from itaca.core.version import __version__
from itaca.io.formats.itc import open_itc as open
from itaca.io.loader import load

__all__ = ["ITACAError", "__version__", "load", "open", "set_mode", "set_user"]
