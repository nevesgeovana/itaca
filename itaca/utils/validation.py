"""Input validation and error formatting helpers.

Re-exports the canonical three-part error message formatter (REQ-81)
so that ``io/`` and ``ops/`` modules can assemble ITACAError messages
from one place. Validation helpers are added here as the operations
that need them arrive (M0 Phases 2 to 5).
"""

from itaca.core.errors import format_error_message

__all__ = ["format_error_message"]
