"""
Dependency-free utilities to list and inspect rixpress build logs.

Behavior:
- No external dependencies (no pandas).
- rxp_list_logs returns a list of dicts with keys:
    - filename (str)
    - modification_time (YYYY-MM-DD string)
    - size_kb (float)
  ordered most recent first.
- rxp_inspect selects a log (most recent or regex match) and returns the JSON
  content coerced into a list-of-dicts (rows).
- Errors: raises FileNotFoundError when _rixpress or logs are missing;
  raises ValueError when which_log is provided but no match is found.
- Uses the standard library logging module to emit an INFO message when a
  specific log is chosen via which_log.

This mirrors the R functions rxp_list_logs and rxp_inspect as closely as possible
while being dependency-free and returning plain Python structures.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pprint import pprint

logger = logging.getLogger(__name__)


def _iso_date_from_epoch(epoch: float) -> str:
    """Return YYYY-MM-DD formatted date string from epoch seconds."""
    return datetime.fromtimestamp(epoch).date().isoformat()



logger = logging.getLogger(__name__)


def _iso_date_from_epoch(epoch: float) -> str:
    """Return YYYY-MM-DD formatted date string from epoch seconds."""
    return datetime.fromtimestamp(epoch).date().isoformat()


def rxp_list_logs(
    project_path: Union[str, Path] = ".",
    pretty: bool = False,
    as_json: bool = False,
) -> Optional[List[Dict[str, Union[str, float]]]]:
    """
    rxp_list_logs

    List build logs in the project's _rixpress directory.

    Parameters:
      - project_path: path to project root (defaults to ".")
      - pretty: if True, pretty-prints the result (and returns nothing).
      - as_json: if True, pretty prints using json.dumps(indent=2) instead of pprint.

    Returns:
      A list of dictionaries, each with keys:
        - filename: basename of log file (str)
        - modification_time: ISO date string YYYY-MM-DD (str)
        - size_kb: file size in kilobytes rounded to 2 decimals (float)
      (unless pretty=True, in which case nothing is returned)

    Raises:
      FileNotFoundError if the _rixpress directory does not exist or if no logs are found.
    """
    proj = Path(project_path)
    rixpress_dir = proj / "_rixpress"

    if not rixpress_dir.exists() or not rixpress_dir.is_dir():
        raise FileNotFoundError("_rixpress directory not found. Did you initialise the project?")

    pattern = re.compile(r"^build_log.*\.json$")
    log_files = [p for p in rixpress_dir.iterdir() if p.is_file() and pattern.search(p.name)]

    # Sort by modification time (most recent first)
    log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if not log_files:
        raise FileNotFoundError(f"No build logs found in {rixpress_dir}")

    logs: List[Dict[str, Union[str, float]]] = []
    for p in log_files:
        st = p.stat()
        logs.append(
            {
                "filename": p.name,
                "modification_time": _iso_date_from_epoch(st.st_mtime),
                "size_kb": round(st.st_size / 1024.0, 2),
            }
        )

    if pretty:
        if as_json:
            print(json.dumps(logs, indent=2, ensure_ascii=False))
        else:
            pprint(logs)
        return

    return logs


def _coerce_json_to_rows(data: Any) -> List[Dict[str, Any]]:
    """
    Coerce loaded JSON into list-of-dicts (rows).

    Handles common shapes:
      - list of dicts -> returned unchanged (each element is a row)
      - dict of equal-length lists (columns) -> converted to list-of-rows
      - single dict -> wrapped as single-row [dict]
      - list of scalars/mixed -> wrapped as [{"value": ...}, ...]

    This is a pragmatic approximation of R's jsonlite::read_json(simplifyVector = TRUE)
    + as.data.frame(...) behavior for the typical logging shapes.
    """
    if isinstance(data, list):
        if all(isinstance(el, dict) for el in data):
            return data  # list of rows already
        # mixed list or scalars -> wrap each element into a dict
        return [{"value": el} for el in data]

    if isinstance(data, dict):
        # If all values are lists and of equal length, treat as columns -> rows
        vals = list(data.values())
        if vals and all(isinstance(v, list) for v in vals):
            lengths = [len(v) for v in vals]
            if len(set(lengths)) == 1:
                n = lengths[0]
                keys = list(data.keys())
                rows: List[Dict[str, Any]] = []
                for i in range(n):
                    row = {k: data[k][i] for k in keys}
                    rows.append(row)
                return rows
        # Fallback: single dict -> single row
        return [data]

    # Other shapes (e.g., string/number) -> wrap
    return [{"value": data}]

def rxp_inspect(
    project_path: Union[str, Path] = ".",
    which_log: Optional[str] = None,
    pretty: bool = False,
    as_json: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    rxp_inspect

    Inspect the build result of a pipeline.

    Parameters:
      - project_path: path to project root (defaults to ".")
      - which_log: optional regex to select a specific log file. If None, the most recent log is used.
      - pretty: if True, pretty-prints the result (and returns nothing).
      - as_json: if True, pretty prints using json.dumps(indent=2) instead of pprint.

    Returns:
      A list of dict rows parsed from the selected JSON log file (unless pretty=True).

    Raises:
      FileNotFoundError if no logs are found or _rixpress missing.
      ValueError if which_log is provided but no matching filename is found.
      RuntimeError if the chosen log cannot be read/parsed.
    """
    proj = Path(project_path)
    rixpress_dir = proj / "_rixpress"

    logs = rxp_list_logs(proj)

    chosen_path: Optional[Path] = None

    if which_log is None:
        chosen_path = rixpress_dir / logs[0]["filename"]
    else:
        import re, logging
        logger = logging.getLogger(__name__)
        pattern = re.compile(which_log)
        for entry in logs:
            if pattern.search(entry["filename"]):
                chosen_path = rixpress_dir / entry["filename"]
                logger.info("Using log file: %s", entry["filename"])
                break
        if chosen_path is None:
            raise ValueError(f"No build logs found matching the pattern: {which_log}")

    try:
        with chosen_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        raise RuntimeError(f"Failed to read log file {chosen_path}: {e}")

    rows = _coerce_json_to_rows(data)

    if pretty:
        if as_json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            pprint(rows)
        return  # This ensures REPL shows nothing after print, return value is None

    return rows
