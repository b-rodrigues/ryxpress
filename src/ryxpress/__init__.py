"""
ryxpress package — lightweight top-level API with lazy submodule imports.

This __init__ is deliberately lightweight so simple imports (like tests that
only check __version__ and hello()) do not fail if optional dependencies of
submodules are missing. Submodules are imported lazily on attribute access.

Module-to-file mapping uses the actual filenames present under src/ryxpress:
- r_runner.py         -> ryxpress.r_runner
- rxp_copy.py         -> ryxpress.rxp_copy
- rxp_gc.py           -> ryxpress.rxp_gc
- rxp_init.py         -> ryxpress.rxp_init
- rxp_inspect.py      -> ryxpress.rxp_inspect
- rxp_read_load.py    -> ryxpress.rxp_read_load
- plot_dag.py         -> ryxpress.plot_dag
- rxp_trace.py        -> ryxpress.rxp_trace
"""
from __future__ import annotations

__version__ = "0.1.0"


def hello() -> str:
    """Small example function to verify the package imports."""
    return "Hello from ryxpress!"


# Lazy mapping: public name -> (module_path, attribute_name_or_None)
# If attribute_name_or_None is None, the module object is returned.
_lazy_imports = {
    "rxp_make": ("ryxpress.r_runner", "rxp_make"),
    "rxp_copy": ("ryxpress.rxp_copy", "rxp_copy"),
    "rxp_gc": ("ryxpress.rxp_gc", "rxp_gc"),
    "rxp_init": ("ryxpress.rxp_init", "rxp_init"),
    "rxp_inspect": ("ryxpress.rxp_inspect", "rxp_inspect"),
    # The read/load helpers are in rxp_read_load.py per your tree.
    "rxp_read": ("ryxpress.rxp_read_load", "rxp_read"),
    "rxp_load": ("ryxpress.rxp_read_load", "rxp_load"),
    "rxp_read_load_setup": ("ryxpress.rxp_read_load", "rxp_read_load_setup"),
    # DAG/plotting helpers (plot_dag.py)
    "rxp_dag_for_ci": ("ryxpress.plot_dag", "rxp_dag_for_ci"),
    "get_nodes_edges": ("ryxpress.plot_dag", "get_nodes_edges"),
    # tracing / other helpers
    "rxp_trace": ("ryxpress.rxp_trace", "rxp_trace"),
}

def __getattr__(name: str):
    """
    Lazy-load attributes from submodules on first access.

    Example:
        from ryxpress import rxp_make   # triggers import ryxpress.r_runner
    """
    if name in _lazy_imports:
        module_path, symbol = _lazy_imports[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
        except Exception as e:
            raise ImportError(
                f"Failed to import optional submodule '{module_path}' required for '{name}'. "
                f"Import the module directly to see details: import {module_path!r}. "
                f"Original error: {e}"
            ) from e

        if symbol is None:
            value = mod
        else:
            try:
                value = getattr(mod, symbol)
            except AttributeError as e:
                raise ImportError(
                    f"Module '{module_path}' does not define expected symbol '{symbol}'."
                ) from e

        # cache for subsequent lookups
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Exports for `from ryxpress import *`
__all__ = ["__version__", "hello"] + list(_lazy_imports.keys())
