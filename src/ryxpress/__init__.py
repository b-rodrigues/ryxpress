"""
ryxpress package — convenience exports and package metadata.

Expose the main public API so users can import functions directly from
the package root:

    from ryxpress import rxp_read, rxp_load, rxp_copy, rxp_gc, rxp_init, rxp_make
"""

__version__ = "0.1.0"

# Public API: import the helper functions implemented in submodules
from .rxp_copy import rxp_copy
from .rxp_read import rxp_read, rxp_load, rxp_read_load_setup
from .rxp_gc import rxp_gc
from .rxp_init import rxp_init
from .rxp_dag import rxp_dag_for_ci, get_nodes_edges
from .r_runner import rxp_make

# Optional: expose a logger for package users
import logging
logger = logging.getLogger(__name__)

__all__ = [
    "__version__",
    "rxp_copy",
    "rxp_read",
    "rxp_load",
    "rxp_read_load_setup",
    "rxp_gc",
    "rxp_init",
    "rxp_dag_for_ci",
    "get_nodes_edges",
    "rxp_make",
    "logger",
]
