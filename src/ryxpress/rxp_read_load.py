"""
Helpers to read/load artifacts from the Nix store for rixpress.

Behavior notes:
- Attempts to load Python pickle artifacts (.pickle or .pkl) using the standard
  library `pickle`. If an artifact is not a pickle file, the functions return
  the path(s) instead of attempting to load.
- If the file is an RDS file (.rds) and the `rds2py` package is available in
  the environment, `rds2py.read_rds()` (or `rds2py.parse_rds()` fallback) is
  used to load the object and the result is returned.
- rxp_read_load_setup mirrors the R helper: if `derivation_name` is a literal
  /nix/store/... path it either returns the single file path (string) or the
  directory path (string) when multiple files are found. Otherwise it inspects
  the build log (via rxp_inspect) and returns either a single path (string) or
  a list of paths.
- rxp_read returns the loaded object when a single supported file is found and
  successfully loaded; otherwise returns path(s).
- rxp_load will load a supported artifact and inject it into the caller's
  globals under the derivation name (best-effort), otherwise returns the path(s).
"""
from __future__ import annotations

import importlib
import inspect
import logging
import os
import pickle
import re
from pathlib import Path
from typing import List, Optional, Sequence, Union

from .rxp_inspect import rxp_inspect

logger = logging.getLogger(__name__)

_PICKLE_EXT_RE = re.compile(r"\.(?:pickle|pkl)$", flags=re.IGNORECASE)
_RDS_EXT_RE = re.compile(r"\.rds$", flags=re.IGNORECASE)


def rxp_read_load_setup(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[str, List[str]]:
    """
    Setup helper for rxp_read and rxp_load.

    Returns:
      - If a single matching file path found: return it as a string.
      - If multiple files are present for the derivation: return a list of file paths.
      - If the caller supplied a /nix/store/... path and it contains multiple files,
        returns the original derivation_name string (mirrors the R behaviour).
    """
    # If derivation_name is already a nix store path, return it (or its single file)
    if isinstance(derivation_name, str) and derivation_name.startswith("/nix/store/"):
        store_path = Path(derivation_name)
        if store_path.is_dir():
            files = [str(p) for p in sorted(store_path.iterdir())]
            if len(files) == 1:
                return files[0]
            else:
                # Mirror R behaviour: return the directory path string if multiple files
                return derivation_name
        else:
            # It's a file path -> return it
            return str(store_path)

    # Otherwise inspect the build log to find the derivation outputs
    rows = rxp_inspect(project_path=project_path, which_log=which_log)
    if not isinstance(rows, list):
        raise RuntimeError("rxp_inspect returned unexpected shape; expected list of rows")

    # Find rows where the derivation column equals derivation_name.
    # Be tolerant about possible key names.
    deriv_keys = ("derivation", "deriv", "name")
    path_key = "path"
    output_key = "output"

    matching_rows = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        deriv_val = None
        for k in deriv_keys:
            if k in r:
                deriv_val = r[k]
                break
        if deriv_val is None:
            continue
        # deriv_val may be scalar or list; normalize to list[str]
        if isinstance(deriv_val, (list, tuple)):
            names = [str(x) for x in deriv_val if x is not None]
        else:
            names = [str(deriv_val)]
        if derivation_name in names:
            matching_rows.append(r)

    if not matching_rows:
        raise ValueError(
            f"No derivation called {derivation_name!r} found. Run rxp_inspect() to check if it was built successfully."
        )

    # Collect outputs: row[path] + "/" + each output in row[output]
    file_paths: List[str] = []
    for r in matching_rows:
        base = r.get(path_key) or r.get("store_path") or r.get("path_store") or r.get("output_path")
        if base is None:
            # If no base path present, skip
            continue
        # Normalize base to string
        base_str = str(base)
        outs = r.get(output_key)
        if outs is None:
            # No explicit outputs listed; treat the derivation path itself
            file_paths.append(base_str)
            continue
        # outputs may be scalar or list; coerce to list
        if isinstance(outs, (list, tuple)):
            out_list = [str(x) for x in outs if x is not None]
        else:
            out_list = [str(outs)]
        for o in out_list:
            # If output already looks like a full path, keep it; else join
            if str(o).startswith("/"):
                file_paths.append(o)
            else:
                file_paths.append(os.path.join(base_str, o))

    # Deduplicate while preserving order
    seen = set()
    deduped: List[str] = []
    for p in file_paths:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    if len(deduped) == 0:
        raise ValueError(f"No outputs recorded for derivation {derivation_name!r} in the build log.")

    # If single path, return it as a string (mirrors R behavior of returning a length-1 char vector)
    if len(deduped) == 1:
        return deduped[0]
    return deduped


def _is_pickle_path(path: str) -> bool:
    return bool(_PICKLE_EXT_RE.search(path))


def _is_rds_path(path: str) -> bool:
    return bool(_RDS_EXT_RE.search(path))


def _load_rds_with_rds2py(path: str):
    """
    Attempt to load an RDS file using rds2py if available.
    Returns the loaded object on success, or None on failure / if rds2py unavailable.
    """
    try:
        mod = importlib.import_module("rds2py")
    except Exception:
        return None
    # Prefer read_rds, fallback to parse_rds
    try:
        if hasattr(mod, "read_rds"):
            return mod.read_rds(path)
        if hasattr(mod, "parse_rds"):
            return mod.parse_rds(path)
        logger.debug("rds2py module found but no read_rds/parse_rds available")
        return None
    except Exception as e:
        logger.warning("rds2py failed to read %s: %s", path, e)
        return None


def rxp_read(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[object, str, List[str]]:
    """
    Read the output of a derivation.

    - If the helper resolves to multiple paths -> returns list[str].
    - If a single path is found:
        - If it's an RDS file and rds2py is available, use rds2py to read it.
        - Else if it's a pickle (.pickle/.pkl) the function attempts to load and return the object.
        - Otherwise returns the path (string).
    """
    resolved = rxp_read_load_setup(derivation_name, which_log=which_log, project_path=project_path)

    # If multiple outputs (list), return them directly
    if isinstance(resolved, list):
        return resolved

    # Single path (string)
    path = str(resolved)

    # If path points to a directory, return it (we only handle file-based artifacts here)
    if os.path.isdir(path):
        return path

    # If it's an RDS and rds2py present, try to use it
    if _is_rds_path(path):
        rds_obj = _load_rds_with_rds2py(path)
        if rds_obj is not None:
            return rds_obj
        # If rds2py not available or failed, return the path (do not attempt pickle)
        return path

    # Only attempt to load pickles; otherwise return path
    if not _is_pickle_path(path):
        return path

    try:
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
        return obj
    except Exception as e:
        logger.warning("Failed to unpickle %s: %s", path, e)
        return path


def rxp_load(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[object, str, List[str]]:
    """
    Load the output of a derivation into the caller's (parent) globals under the name
    `derivation_name`, if a single supported file is available and successfully loaded.

    Otherwise returns the path(s) (string or list[str]) without assigning.

    Returns the loaded object on success (and assigns it); otherwise returns path(s).
    """
    resolved = rxp_read_load_setup(derivation_name, which_log=which_log, project_path=project_path)

    # If multiple outputs, return them
    if isinstance(resolved, list):
        return resolved

    path = str(resolved)

    if os.path.isdir(path):
        return path

    # Try RDS via rds2py first (if applicable)
    if _is_rds_path(path):
        rds_obj = _load_rds_with_rds2py(path)
        if rds_obj is None:
            return path
        # Assign into caller's globals
        try:
            caller_frame = inspect.currentframe().f_back
            if caller_frame is not None:
                caller_globals = caller_frame.f_globals
                caller_globals[derivation_name] = rds_obj
        except Exception:
            logger.debug("Failed to assign RDS-loaded object into caller globals", exc_info=True)
        return rds_obj

    # Then try pickle
    if not _is_pickle_path(path):
        return path

    try:
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
    except Exception as e:
        logger.warning("Failed to unpickle %s: %s", path, e)
        return path

    # Assign into caller's globals (closest approximation of R's parent.frame())
    try:
        caller_frame = inspect.currentframe().f_back
        if caller_frame is not None:
            caller_globals = caller_frame.f_globals
            caller_globals[derivation_name] = obj
    except Exception:
        logger.debug("Failed to assign loaded object into caller globals", exc_info=True)

    return obj
