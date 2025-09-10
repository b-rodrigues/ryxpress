"""
ryxpress package — lightweight top-level API with lazy submodule imports.

This __init__ is deliberately lightweight so simple imports (like tests that
only check __version__ and hello()) do not fail if optional dependencies of
submodules are missing. Submodules are imported lazily on attribute access.

Module-to-file mapping uses the actual filenames present under src/ryxpress:
- r_runner.py          -> ryxpress.r_runner
- copy_artifacts.py    -> ryxpress.rxp_copy
- garbage.py           -> ryxpress.rxp_gc
- init_proj.py         -> ryxpress.rxp_init
- inspect_logs.py      -> ryxpress.rxp_inspect, ryxpress.rxp_list_logs
- read_load.py         -> ryxpress.rxp_read_load
- plotting.py          -> ryxpress.plot_dag
- tracing.py           -> ryxpress.rxp_trace
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
    "rxp_copy": ("ryxpress.copy_artifacts", "rxp_copy"),
    "rxp_gc": ("ryxpress.garbage", "rxp_gc"),
    "rxp_init": ("ryxpress.init_proj", "rxp_init"),
    "rxp_list_logs": ("ryxpress.inspect_logs", "rxp_list_logs"),
    "rxp_inspect": ("ryxpress.inspect_logs", "rxp_inspect"),
    # The read/load helpers are in rxp_read_load.py per your tree.
    "rxp_read_load": ("ryxpress.read_load", "rxp_read_load"),
    "rxp_read": ("ryxpress.read_load", "rxp_read"),
    "rxp_load": ("ryxpress.read_load", "rxp_load"),
    # DAG/plotting helpers (plot_dag.py)
    "rxp_dag_for_ci": ("ryxpress.plotting", "rxp_dag_for_ci"),
    # tracing / other helpers
    "rxp_trace": ("ryxpress.tracing", "rxp_trace"),
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
