"""
Helpers to read/load artifacts from the Nix store for ryxpress.

Behavior:

- Resolve derivation outputs (single path or list of paths) via rxp_inspect
  or by accepting a literal /nix/store/... path.
- When a single file is resolved:
  - Try to unpickle the file first (regardless of extension). If that succeeds,
    return the loaded object.
  - Otherwise try to load using rds2py (if available) and return that object.
  - If neither works, return the path (string) — do not raise or warn.
- If multiple outputs are resolved, return the list of paths.
- The functions intentionally avoid raising errors or emitting warnings for
  normal "can't load this artifact" cases; they prefer to return the path(s).
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

from .inspect_logs import rxp_inspect

logger = logging.getLogger(__name__)

_PICKLE_EXT_RE = re.compile(r"\.(?:pickle|pkl)$", flags=re.IGNORECASE)
_RDS_EXT_RE = re.compile(r"\.rds$", flags=re.IGNORECASE)


def rxp_read_load_setup(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[str, List[str]]:
    """
    Resolve derivation outputs.

    Returns:
      - single path as str if only one output resolved,
      - list[str] if multiple outputs resolved,
      - otherwise returns the original derivation_name (no exceptions raised here).
    """
    # If given an explicit /nix/store path, handle directly
    if isinstance(derivation_name, str) and derivation_name.startswith("/nix/store/"):
        store_path = Path(derivation_name)
        try:
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
        except Exception:
            # On any filesystem error, fall back to returning the original string
            return derivation_name

    # Otherwise, attempt to inspect build log; but do not raise on failure.
    try:
        rows = rxp_inspect(project_path=project_path, which_log=which_log)
    except Exception:
        # If inspection fails for any reason, return the original derivation_name
        return derivation_name

    if not isinstance(rows, list):
        return derivation_name

    # Find rows where the derivation column equals derivation_name.
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
        if isinstance(deriv_val, (list, tuple)):
            names = [str(x) for x in deriv_val if x is not None]
        else:
            names = [str(deriv_val)]
        if derivation_name in names:
            matching_rows.append(r)

    if not matching_rows:
        # Do not raise; return the original caller-supplied name
        return derivation_name

    # Collect outputs
    file_paths: List[str] = []
    for r in matching_rows:
        base = r.get(path_key) or r.get("store_path") or r.get("path_store") or r.get("output_path")
        if base is None:
            continue
        base_str = str(base)
        outs = r.get(output_key)
        if outs is None:
            file_paths.append(base_str)
            continue
        if isinstance(outs, (list, tuple)):
            out_list = [str(x) for x in outs if x is not None]
        else:
            out_list = [str(outs)]
        for o in out_list:
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
        # No outputs found; return original derivation_name instead of raising
        return derivation_name

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
    Silent on failure (no warnings/errors).
    """
    try:
        mod = importlib.import_module("rds2py")
    except Exception:
        return None
    try:
        if hasattr(mod, "read_rds"):
            return mod.read_rds(path)
        if hasattr(mod, "parse_rds"):
            return mod.parse_rds(path)
        return None
    except Exception:
        # Silent failure
        logger.debug("rds2py failed to read %s", path, exc_info=True)
        return None


def rxp_read(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[object, str, List[str]]:
    """
    rxp_read

    Read the output of a derivation.

    Behavior:

    - If resolved to multiple paths -> return list[str].
    - If single path:
        1. If path is a directory -> return the path string.
        2. Try to pickle.load the file (regardless of extension). If successful, return object.
        3. Try rds2py (if available) to parse; if successful, return object.
        4. Otherwise return the path string.

    All failures are silent; no exceptions/warnings are raised for "can't load" cases.
    """
    resolved = rxp_read_load_setup(derivation_name, which_log=which_log, project_path=project_path)

    # If multiple outputs (list), return them directly
    if isinstance(resolved, list):
        return resolved

    # Single path (string) or fallback value (derivation_name)
    path = str(resolved)

    # If path points to a directory, return it
    if os.path.isdir(path):
        return path

    # Try to unpickle first (regardless of extension)
    try:
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
        return obj
    except Exception:
        # Silent failure — try the next loader
        logger.debug("pickle load failed for %s; will try rds2py if available", path, exc_info=True)

    # Try rds2py as a fallback (regardless of extension)
    rds_obj = _load_rds_with_rds2py(path)
    if rds_obj is not None:
        return rds_obj

    # Nothing worked; return the path string (no errors/warnings)
    return path


def rxp_load(
    derivation_name: str,
    which_log: Optional[str] = None,
    project_path: Union[str, Path] = ".",
) -> Union[object, str, List[str]]:
    """
    rxp_load

    Load the output of a derivation into the caller's globals under the name
    `derivation_name` if successfully loaded as an object.

    Otherwise return the path(s) (string or list[str]). Silent on failures.
    """
    resolved = rxp_read_load_setup(derivation_name, which_log=which_log, project_path=project_path)

    # If multiple outputs, return them
    if isinstance(resolved, list):
        return resolved

    path = str(resolved)

    if os.path.isdir(path):
        return path

    # Try to unpickle first
    try:
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
    except Exception:
        obj = None
        logger.debug("pickle load failed for %s; will try rds2py if available", path, exc_info=True)

    # If pickle failed, try rds2py
    if obj is None:
        obj = _load_rds_with_rds2py(path)

    if obj is None:
        # Nothing we can load silently; return the path
        return path

    # Assign into caller's globals (best-effort); silence any assignment errors
    try:
        caller_frame = inspect.currentframe().f_back
        if caller_frame is not None:
            caller_globals = caller_frame.f_globals
            # Use derivation_name as the variable name; keep last path component if it's a path
            try:
                var_name = derivation_name
                # If derivation_name looks like a path, use the basename without extension
                if derivation_name.startswith("/nix/store/") or os.path.sep in derivation_name:
                    var_name = os.path.splitext(os.path.basename(str(path)))[0]
                # ensure valid identifier fallback
                if not var_name.isidentifier():
                    var_name = "_".join(re.findall(r"\w+", var_name)) or "loaded_artifact"
            except Exception:
                var_name = "loaded_artifact"
            caller_globals[var_name] = obj
    except Exception:
        logger.debug("Failed to assign loaded object into caller globals", exc_info=True)

    return obj
