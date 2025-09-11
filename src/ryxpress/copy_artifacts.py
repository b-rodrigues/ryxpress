"""
Copy derivations from the Nix store to the current working directory.

Translation of R's rxp_copy to a dependency-free Python function.

Behavior:

- Uses rxp_inspect to read the most recent build log and find derivation
  entries and their store paths.
- Copies the outputs of a single derivation (or the special "all-derivations")
  into ./pipeline-output (created if necessary).
- Applies POSIX permission modes to directories and files (dir_mode/file_mode
  are octal strings like "0755" or "755").
- Returns None; raises exceptions on errors.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union

from .inspect_logs import rxp_inspect, rxp_list_logs

logger = logging.getLogger(__name__)


def _valid_mode(mode: str) -> bool:
    return isinstance(mode, str) and re.match(r"^[0-7]{3,4}$", mode) is not None


def _to_mode_int(mode: str) -> int:
    # Accept "755" or "0755"
    if not _valid_mode(mode):
        raise ValueError(f'Invalid mode: "{mode}". Provide octal like "0755" or "755".')
    return int(mode, 8)


def _apply_permissions(root_dir: Path, dir_mode: str, file_mode: str) -> None:
    """
    Recursively set POSIX permissions for all directories and files under root_dir.
    Best-effort; failures are ignored (mirroring R's suppressWarnings).
    """
    try:
        dmode = _to_mode_int(dir_mode)
        fmode = _to_mode_int(file_mode)
    except ValueError:
        # Should not happen because validated earlier, but be defensive
        return

    # Apply to root_dir itself (if it exists)
    try:
        if root_dir.exists():
            os.chmod(root_dir, dmode)
    except Exception:
        logger.debug("Failed to chmod directory %s", root_dir)

    # Walk the tree and apply modes
    for dirpath, dirnames, filenames in os.walk(root_dir):
        try:
            os.chmod(dirpath, dmode)
        except Exception:
            logger.debug("Failed to chmod directory %s", dirpath)
        for fname in filenames:
            fpath = Path(dirpath) / fname
            try:
                os.chmod(fpath, fmode)
            except Exception:
                logger.debug("Failed to chmod file %s", fpath)
        # ensure subdirectories get the directory mode on next loop iteration


def _ensure_output_dir(base: Path) -> Path:
    out = base / "pipeline-output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _extract_field(row: Dict, candidates: Sequence[str]) -> Optional[Union[str, Sequence[str]]]:
    """
    Extract the first available candidate field from a row (case-sensitive),
    returning None if none found.
    """
    for k in candidates:
        if k in row:
            return row[k]
    return None


def _ensure_iterable_of_strings(val) -> List[str]:
    """
    Convert a value to a list of strings:
    - if string -> [string]
    - if list/tuple -> flatten items to strings
    - otherwise -> []
    """
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, (list, tuple)):
        out = []
        for el in val:
            if el is None:
                continue
            out.append(str(el))
        return out
    # fallback
    return [str(val)]


def rxp_copy(
    derivation_name: Optional[str] = None,
    dir_mode: str = "0755",
    file_mode: str = "0644",
    project_path: Union[str, Path] = ".",
) -> None:
    """
    rxp_copy

    Copy derivations from the Nix store to ./pipeline-output.

    Parameters:

      - derivation_name: name of the derivation to copy (string). If None,
        uses the special derivation name "all-derivations" (mirrors R).
      - dir_mode / file_mode: octal permission strings applied to copied dirs/files.
      - project_path: project root where _rixpress lives (defaults to ".").

    Raises:

      - FileNotFoundError if _rixpress or logs are missing.
      - ValueError on invalid modes or derivation not found.
      - RuntimeError on copy failures.
    """
    project = Path(project_path)
    # Validate modes
    if not _valid_mode(dir_mode):
        raise ValueError('Invalid dir_mode: provide a character octal like "0755" or "755".')
    if not _valid_mode(file_mode):
        raise ValueError('Invalid file_mode: provide a character octal like "0644" or "644".')

    # Ensure there is a build log
    logs = rxp_list_logs(project)
    # rxp_list_logs raises if none; if it returned, we have log entries

    # Read latest build log content via rxp_inspect (most recent)
    rows = rxp_inspect(project_path=project, which_log=None)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Could not read build log details; rxp_inspect returned no rows.")

    # Build a mapping from derivation name -> list of store paths
    # We try to be tolerant: look for keys 'derivation' (R), then 'deriv', 'name'
    deriv_key_candidates = ("derivation", "deriv", "name")
    path_key_candidates = ("path", "store_path", "path_store", "output_path", "output")

    deriv_to_paths: Dict[str, List[str]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        deriv_val = _extract_field(r, deriv_key_candidates)
        path_val = _extract_field(r, path_key_candidates)
        if deriv_val is None:
            # skip rows without a derivation name
            continue
        derivs = _ensure_iterable_of_strings(deriv_val)
        paths = _ensure_iterable_of_strings(path_val)
        for d in derivs:
            deriv_to_paths.setdefault(d, []).extend(paths)

    # Deduplicate path lists
    for k in list(deriv_to_paths.keys()):
        seen = []
        for p in deriv_to_paths[k]:
            if p not in seen:
                seen.append(p)
        deriv_to_paths[k] = seen

    # Choose derivation_name if not provided
    if derivation_name is None:
        derivation_name = "all-derivations"

    if derivation_name not in deriv_to_paths:
        # Provide hint of available derivations (up to 20)
        available = list(deriv_to_paths.keys())[:20]
        more = ", ..." if len(deriv_to_paths) > 20 else ""
        raise ValueError(
            f"No derivation {derivation_name!r} found in the build log. Available: {', '.join(available)}{more}"
        )

    # Collect paths for this derivation
    deriv_paths = deriv_to_paths.get(derivation_name, [])
    if not deriv_paths:
        raise RuntimeError(f"No store paths recorded for derivation {derivation_name!r} in the build log.")

    output_dir = _ensure_output_dir(Path.cwd())

    # For each store path, copy its contents into output_dir
    copy_failed = False
    errors: List[str] = []
    for store_path_str in deriv_paths:
        store_path = Path(store_path_str)
        if not store_path.exists():
            # Skip non-existing path (warn)
            logger.warning("Store path does not exist, skipping: %s", store_path)
            continue
        try:
            # If the derivation path is a directory, copy its children into output_dir
            if store_path.is_dir():
                # copy each child into output_dir, preserving names
                for child in store_path.iterdir():
                    dest = output_dir / child.name
                    if child.is_dir():
                        # Python 3.8+: dirs_exist_ok True will merge
                        try:
                            shutil.copytree(child, dest, dirs_exist_ok=True)
                        except TypeError:
                            # older Python: fallback to manual merge
                            if dest.exists():
                                # copy contents into existing dest
                                for sub in child.rglob("*"):
                                    rel = sub.relative_to(child)
                                    target = dest / rel
                                    if sub.is_dir():
                                        target.mkdir(parents=True, exist_ok=True)
                                    else:
                                        target.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(sub, target)
                            else:
                                shutil.copytree(child, dest)
                    else:
                        # file: copy, possibly overwrite
                        shutil.copy2(child, dest)
            else:
                # store_path is a file: copy into output_dir
                dest_file = output_dir / store_path.name
                shutil.copy2(store_path, dest_file)
        except Exception as e:
            copy_failed = True
            errors.append(f"{store_path}: {e}")
            logger.debug("Copy error for %s: %s", store_path, e)

    # Apply permissions
    try:
        _apply_permissions(output_dir, dir_mode=dir_mode, file_mode=file_mode)
    except Exception:
        # Best-effort: ignore permission application errors
        logger.debug("Failed to apply permissions to %s", output_dir)

    if copy_failed:
        raise RuntimeError(f"Copy unsuccessful: errors occurred:\n" + "\n".join(errors))

    # Success message
    print(f"Copy successful, check out {output_dir}")
    return None
