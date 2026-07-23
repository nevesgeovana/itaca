"""ITACA: Integrated Toolkit for Aerospace Computation and Analysis.

From data to wisdom. Import convention::

    import itaca as itc
"""

from itaca.core.accessors import register_accessor
from itaca.core.axes import Axis
from itaca.core.errors import ITACAError
from itaca.core.pipeline import Pipeline, load_pipeline
from itaca.core.provenance import set_mode, set_user
from itaca.core.sentinels import no_default
from itaca.core.varframe import VarFrame
from itaca.core.version import __version__
from itaca.io.formats.itc import open_itc as open
from itaca.io.loader import load
from itaca.ops.concat import concat

__all__ = [
    "Axis",
    "ITACAError",
    "Pipeline",
    "VarFrame",
    "__version__",
    "concat",
    "load",
    "load_pipeline",
    "no_default",
    "open",
    "register_accessor",
    "set_mode",
    "set_user",
]
