"""
Garbage collect rixpress build artifacts and logs.

Improved translation of the R function rxp_gc to Python with robust cleanup:
- Atomic lock file creation to avoid races
- Signal handlers (SIGINT/SIGTERM) to ensure cleanup on interruption
- Temporary GC roots are recorded and removed after the operation (so they
  don't keep artifacts alive forever)
- 'ask' parameter to control interactive confirmation (defaults to True)
- Summary dict always contains canonical keys
- Dependency-free (standard library only)
"""
from __future__ import annotations

import errno
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union
from pprint import pprint

from .inspect_logs import rxp_inspect, rxp_list_logs

logger = logging.getLogger(__name__)


class RxpGCError(RuntimeError):
    pass


_NIX_STORE_RE = re.compile(r"^/nix/store/[a-z0-9]{32}-")
_WHICH_LOG_RE = re.compile(r"build_log_[0-9]{8}_([0-9]{6})_")


def _safe_run(cmd: Sequence[str], timeout: int = 300, check: bool = True) -> Tuple[int, str, str]:
    """Run command, return (returncode, stdout, stderr). Raise RxpGCError on timeouts or if check and non-zero."""
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RxpGCError(f"Command '{cmd[0]}' timed out after {timeout} seconds.") from e
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = (stdout + "\n" + stderr).strip()
    if check and proc.returncode != 0:
        raise RxpGCError(f"Command '{' '.join(cmd)}' failed (exit {proc.returncode}).\n{combined}")
    return proc.returncode, stdout, stderr


def _validate_store_paths(paths: Sequence[str]) -> List[str]:
    """Filter and return unique, existing nix store paths matching the expected pattern."""
    if not paths:
        return []
    seen = set()
    out = []
    for p in paths:
        if not isinstance(p, str):
            continue
        p = p.strip()
        if not p:
            continue
        if p in seen:
            continue
        if not _NIX_STORE_RE.match(p):
            continue
        # We intentionally allow reporting paths that may not exist at the time
        # of discovery, but most checks in deletion only operate on existing ones.
        if os.path.exists(p) or os.path.isdir(p):
            out.append(p)
            seen.add(p)
    return out


def _extract_which_log(filename: str) -> Optional[str]:
    m = _WHICH_LOG_RE.search(filename)
    if not m:
        return None
    return m.group(1)


def _parse_iso_date(s: str) -> date:
    # Accept ISO YYYY-MM-DD (rxp_list_logs returns YYYY-MM-DD per earlier implementation)
    # Also accept datetime.isoformat and fallback to date-only string.
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        # fallback: take the date part
        try:
            return datetime.strptime(s.split("T", 1)[0], "%Y-%m-%d").date()
        except Exception as e:
            raise ValueError(f"Invalid date string: {s}") from e


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    """Ask user yes/no; mimic utils::askYesNo default behaviour. Non-interactive => return default."""
    try:
        if not (hasattr(os.sys.stdin, "isatty") and os.sys.stdin.isatty()):
            logger.info("Non-interactive session; defaulting to %s for prompt: %s", default, prompt)
            return default
        val = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        return val in ("y", "yes")
    except Exception:
        return default


class LockFile:
    """Context manager for atomic lock file with basic staleness handling."""

    def __init__(self, path: Union[str, Path], timeout_sec: int = 300):
        self.path = Path(path)
        self.timeout_sec = timeout_sec
        self.acquired = False
        self.fd = None

    def _write_lock(self):
        now = datetime.now().isoformat()
        pid = os.getpid()
        # Write using the file descriptor we created atomically
        os.write(self.fd, f"{pid}\n{now}\n".encode("utf-8"))
        os.fsync(self.fd)

    def _is_stale(self, timestamp_str: str) -> bool:
        try:
            ts = datetime.fromisoformat(timestamp_str)
        except Exception:
            return True
        return (datetime.now() - ts).total_seconds() > self.timeout_sec

    def acquire(self):
        # Try atomic creation
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        mode = 0o644
        try:
            self.fd = os.open(str(self.path), flags, mode)
            self._write_lock()
            self.acquired = True
            return True
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            # Lock file exists: examine it for staleness
            try:
                content = self.path.read_text().splitlines()
                if len(content) >= 2:
                    try:
                        pid = int(content[0])
                    except Exception:
                        pid = None
                    tstamp = content[1]
                else:
                    pid = None
                    tstamp = None
            except Exception:
                pid = None
                tstamp = None

            # If a PID is present and exists on POSIX, consider it alive
            alive = False
            if pid is not None and os.name == "posix":
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
            # If alive and recent, fail
            if alive and tstamp is not None:
                try:
                    ts = datetime.fromisoformat(tstamp)
                    if (datetime.now() - ts).total_seconds() <= self.timeout_sec:
                        raise RxpGCError(f"Another rxp_gc process appears to be running (PID: {pid}). If not, remove the lock: {self.path}")
                except ValueError:
                    # can't parse timestamp: be conservative and fail
                    raise RxpGCError(f"Lock file present and appears active: {self.path}")

            # If not alive or lock is stale, remove it and retry atomic creation once
            try:
                self.path.unlink()
            except Exception:
                raise RxpGCError(f"Could not remove stale lock file: {self.path}")
            # Retry atomic creation
            try:
                self.fd = os.open(str(self.path), flags, mode)
                self._write_lock()
                self.acquired = True
                return True
            except OSError as e2:
                raise RxpGCError(f"Failed to create lock file: {e2}") from e2

    def release(self):
        if self.acquired:
            try:
                if self.fd is not None:
                    os.close(self.fd)
            except Exception:
                pass
            try:
                if self.path.exists():
                    self.path.unlink()
            except Exception:
                pass
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def rxp_gc(
    keep_since: Optional[Union[str, date]] = None,
    project_path: Union[str, Path] = ".",
    dry_run: bool = True,
    timeout_sec: int = 300,
    verbose: bool = False,
    ask: bool = True,
    pretty: bool = False,
    as_json: bool = False,
) -> Dict[str, object]:
    """
    rxp_gc

    Garbage collect Nix store paths and build logs produced by rixpress.

    Parameters

    - keep_since: None for full GC, or a date/ISO date string (YYYY-MM-DD) to keep logs newer-or-equal to that date.
    - project_path: project root containing _rixpress
    - dry_run: if True, show what would be deleted without deleting
    - timeout_sec: timeout for invoked nix-store commands and for lock staleness checks
    - verbose: if True, print extra diagnostic output
    - ask: if True, prompt for confirmation before destructive operations (default True)

    Returns:

      A summary dict with canonical keys:
        kept, deleted, protected, deleted_count, failed_count, referenced_count,
        log_files_deleted, log_files_failed, dry_run_details
    """
    nix_bin = shutil.which("nix-store")
    if not nix_bin:
        raise FileNotFoundError("nix-store not found on PATH. Install Nix or adjust PATH.")

    project_path = Path(project_path).resolve()
    if not project_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    lock_file_path = Path(tempfile.gettempdir()) / "rixpress_gc.lock"

    # record of temp gcroot symlink paths we created so we can remove them later
    created_gcroot_links: List[Path] = []

    # ensure we cleanup on signals
    def _cleanup_on_signal(signum, frame):
        logger.info("Received signal %s, cleaning up...", signum)
        # remove any gcroot links
        for p in created_gcroot_links:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        # remove lock file if held
        try:
            if lock_path_context and lock_path_context.acquired:
                lock_path_context.release()
        except Exception:
            pass
        raise SystemExit(1)

    # placeholder for context so signal handler can access
    lock_path_context: Optional[LockFile] = None

    # Register handlers
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _cleanup_on_signal)
    signal.signal(signal.SIGTERM, _cleanup_on_signal)

    try:
        # Acquire lock with context manager (atomic)
        lock_path_context = LockFile(lock_file_path, timeout_sec=timeout_sec)
        lock_path_context.acquire()

        # parse keep_since
        if keep_since is not None:
            if isinstance(keep_since, date) and not isinstance(keep_since, datetime):
                keep_date = keep_since
            else:
                # accept YYYY-MM-DD string
                try:
                    keep_date = _parse_iso_date(str(keep_since))
                except Exception:
                    raise ValueError("Invalid 'keep_since'. Use a date or 'YYYY-MM-DD' string.")
        else:
            keep_date = None

        # Gather logs
        all_logs = rxp_list_logs(project_path)
        # Expect list of dicts with 'filename' and 'modification_time'
        if not isinstance(all_logs, list) or not all_logs:
            logger.info("No build logs found. Nothing to do.")
            # canonical empty summary
            return {
                "kept": [],
                "deleted": [],
                "protected": 0,
                "deleted_count": 0,
                "failed_count": 0,
                "referenced_count": 0,
                "log_files_deleted": 0,
                "log_files_failed": 0,
                "dry_run_details": None,
            }

        # Partition logs
        logs_to_keep = []
        logs_to_delete = []
        for entry in all_logs:
            fn = entry.get("filename")
            mtime = entry.get("modification_time")
            if not fn or not mtime:
                continue
            try:
                mdate = _parse_iso_date(mtime)
            except Exception:
                # If malformed, treat as older than keep_since to be conservative
                mdate = datetime.min.date()
            if keep_date is None:
                logs_to_keep.append(entry)
            else:
                if mdate >= keep_date:
                    logs_to_keep.append(entry)
                else:
                    logs_to_delete.append(entry)

        def _filenames(entries: Sequence[Dict]) -> List[str]:
            return [e["filename"] for e in entries]

        # helper to get store paths per log using rxp_inspect
        def get_paths_from_logs(filenames: Sequence[str]) -> Dict[str, List[str]]:
            out: Dict[str, List[str]] = {}
            for fn in filenames:
                wl = _extract_which_log(fn)
                if wl is None:
                    logger.warning("Could not parse which_log from filename: %s", fn)
                    out[fn] = []
                    continue
                try:
                    insp_rows = rxp_inspect(project_path=project_path, which_log=wl)
                except Exception as e:
                    logger.warning("rxp_inspect failed for %s: %s", fn, e)
                    out[fn] = []
                    continue
                # rxp_inspect returns list of dicts; look for 'path' keys
                paths = []
                if isinstance(insp_rows, list):
                    for row in insp_rows:
                        if isinstance(row, dict) and "path" in row and isinstance(row["path"], str):
                            paths.append(row["path"])
                out[fn] = _validate_store_paths(paths)
            return out

        keep_paths_by_log = get_paths_from_logs(_filenames(logs_to_keep)) if logs_to_keep else {}
        delete_paths_by_log = get_paths_from_logs(_filenames(logs_to_delete)) if logs_to_delete else {}

        keep_paths_all = _validate_store_paths(sorted({p for lst in keep_paths_by_log.values() for p in lst}))
        delete_paths_all = _validate_store_paths(sorted({p for lst in delete_paths_by_log.values() for p in lst}))

        summary_info: Dict[str, object] = {
            "kept": _filenames(logs_to_keep),
            "deleted": _filenames(logs_to_delete),
            "protected": 0,
            "deleted_count": 0,
            "failed_count": 0,
            "referenced_count": 0,
            "log_files_deleted": 0,
            "log_files_failed": 0,
            "dry_run_details": None,
        }

        # DRY RUN branch (date-based)
        if keep_date is not None and dry_run:
            logger.info("--- DRY RUN --- No changes will be made. ---")
            logger.info("Logs that would be deleted (%d):", len(logs_to_delete))
            for fn in summary_info["deleted"]:
                logger.info("  %s", fn)
            details: Dict[str, List[Dict[str, str]]] = {}
            if delete_paths_by_log:
                logger.info("Artifacts per log (from rxp_inspect):")
                for fn, _ in delete_paths_by_log.items():
                    logger.info("== %s ==", fn)
                    try:
                        insp_rows = rxp_inspect(project_path=project_path, which_log=_extract_which_log(fn) or "")
                    except Exception:
                        logger.info("  (rxp_inspect unavailable)")
                        details[fn] = []
                        continue
                    rows = []
                    if isinstance(insp_rows, list):
                        for r in insp_rows:
                            if not isinstance(r, dict):
                                continue
                            rows.append({"path": r.get("path", ""), "output": r.get("output", "")})
                    details[fn] = rows
            existing_delete_paths = [p for p in delete_paths_all if os.path.exists(p) or os.path.isdir(p)]
            missing_paths = [p for p in delete_paths_all if p not in existing_delete_paths]
            logger.info("Aggregate store paths targeted for deletion (deduped): %d total, %d existing, %d missing",
                        len(delete_paths_all), len(existing_delete_paths), len(missing_paths))
            if existing_delete_paths:
                logger.info("Existing paths that would be deleted:")
                for p in existing_delete_paths:
                    logger.info("  %s", p)
            if missing_paths:
                logger.info("Paths already missing (will be skipped):")
                for p in missing_paths:
                    logger.info("  %s", p)
            summary_info["dry_run_details"] = details
            if logs_to_delete:
                logger.info("Build log files that would be deleted:")
                for fn in summary_info["deleted"]:
                    log_path = project_path / "_rixpress" / fn
                    exists_indicator = "[OK]" if log_path.exists() else "[X]"
                    logger.info("  %s %s", exists_indicator, fn)
            if pretty:
                if as_json:
                    print(json.dumps(summary_info, indent=2, ensure_ascii=False))
                else:
                    pprint(summary_info)
                return

            return summary_info

        # dry-run full GC preview
        if keep_date is None and dry_run:
            logger.info("--- DRY RUN --- Would run 'nix-store --gc' (delete all unreferenced store paths). ---")
            if verbose:
                logger.info("(Tip: for an approximate preview, run 'nix-collect-garbage -n' from a shell.)")
            return summary_info

        # Full GC mode
        if keep_date is None:
            if ask:
                proceed = _ask_yes_no("Run full Nix garbage collection (delete all unreferenced artifacts)?", default=False)
                if not proceed:
                    logger.info("Operation cancelled.")
                    return summary_info
            logger.info("Running Nix garbage collector...")
            try:
                _, stdout, stderr = _safe_run([nix_bin, "--gc"], timeout=timeout_sec, check=True)
                if stdout:
                    if verbose:
                        logger.info(stdout)
                    else:
                        rel = [l for l in stdout.splitlines() if re.search(r"freed|removing|deleting", l, re.I)]
                        if rel:
                            for line in rel[-10:]:
                                logger.info(line)
                logger.info("Garbage collection complete.")
                return summary_info
            except RxpGCError as e:
                raise

        # Targeted deletion mode
        if not logs_to_delete:
            logger.info("No build logs older than %s found. Nothing to do.", keep_date.isoformat())
            return summary_info

        if not delete_paths_all:
            logger.info("No valid store paths found in logs older than %s. Nothing to delete.", keep_date.isoformat())
            return summary_info

        prompt = f"This will permanently delete {len(delete_paths_all)} store paths from {len(logs_to_delete)} build(s) older than {keep_date.isoformat()}. Continue?"
        if ask:
            if not _ask_yes_no(prompt, default=False):
                logger.info("Operation cancelled.")
                return summary_info

        # Protect recent artifacts (date-based mode only) by adding indirect GC roots.
        temp_gcroots_dir: Optional[Path] = None
        protected = 0
        try:
            if keep_paths_all:
                temp_gcroots_dir = Path(tempfile.mkdtemp(prefix="rixpress-gc-"))
                logger.info("Protecting %d recent artifacts via GC roots...", len(keep_paths_all))
                for i, p in enumerate(keep_paths_all, start=1):
                    link_path = temp_gcroots_dir / f"root-{i}"
                    try:
                        # create a placeholder link path (the nix-store --add-root will create the gcroot)
                        # use link_path as the path to register the indirect root
                        _safe_run([nix_bin, "--add-root", str(link_path), "--indirect", p], timeout=timeout_sec, check=True)
                        created_gcroot_links.append(link_path)
                        protected += 1
                    except RxpGCError as e:
                        logger.warning("Failed to add GC root for %s: %s", p, e)
                if protected == 0:
                    raise RxpGCError("Failed to protect any store paths. Aborting.")
                summary_info["protected"] = protected

            # Delete specific store paths
            logger.info("Deleting %d targeted store paths...", len(delete_paths_all))
            existing_paths = [p for p in delete_paths_all if os.path.exists(p) or os.path.isdir(p)]
            missing_paths = [p for p in delete_paths_all if p not in existing_paths]
            if missing_paths:
                logger.info("Skipping %d paths that no longer exist.", len(missing_paths))
                if verbose:
                    for p in missing_paths:
                        logger.info("  Missing: %s", p)
            if not existing_paths:
                logger.info("No existing paths to delete. All targeted paths are already gone.")
                return summary_info

            total_deleted = 0
            failed_paths: List[str] = []
            referenced_paths: List[str] = []

            for i, pth in enumerate(existing_paths, start=1):
                if not (os.path.exists(pth) or os.path.isdir(pth)):
                    logger.info("  [%d/%d] Skipping %s (already gone)", i, len(existing_paths), os.path.basename(pth))
                    continue
                logger.info("  [%d/%d] Attempting to delete %s...", i, len(existing_paths), os.path.basename(pth))
                try:
                    proc = subprocess.run([nix_bin, "--delete", pth], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec)
                    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                    if proc.returncode == 0:
                        total_deleted += 1
                        logger.info("    [OK] Successfully deleted")
                        if verbose and out.strip():
                            logger.info("    %s", out.strip())
                    else:
                        if re.search(r"still alive|Cannot delete", out, re.I):
                            referenced_paths.append(pth)
                            logger.info("    [!] Skipped (still referenced)")
                            if verbose:
                                logger.info("    Details: %s", out.strip())
                        else:
                            failed_paths.append(pth)
                            logger.info("    [X] Failed to delete")
                            if verbose:
                                logger.info("    Details: %s", out.strip())
                except subprocess.TimeoutExpired:
                    failed_paths.append(pth)
                    logger.info("    [X] Timeout while deleting")
                except Exception as e:
                    failed_paths.append(pth)
                    logger.info("    [X] Error: %s", e)

            # Summary of deletion
            logger.info("\nDeletion summary:")
            logger.info("  Successfully deleted: %d paths", total_deleted)
            logger.info("  Skipped (still referenced): %d paths", len(referenced_paths))
            logger.info("  Failed (other errors): %d paths", len(failed_paths))

            if referenced_paths and verbose:
                logger.info("\nReferenced paths (cannot delete):")
                for pth in referenced_paths:
                    logger.info("  %s", os.path.basename(pth))
                    try:
                        _, roots_out, _ = _safe_run([nix_bin, "--query", "--roots", pth], timeout=timeout_sec, check=False)
                        if roots_out.strip():
                            logger.info("    GC roots: %s", roots_out.strip().replace("\n", ", "))
                        else:
                            logger.info("    GC roots: (none found)")
                    except Exception:
                        logger.info("    GC roots: (query failed)")
                    try:
                        _, refs_out, _ = _safe_run([nix_bin, "--query", "--referrers", pth], timeout=timeout_sec, check=False)
                        if refs_out.strip():
                            refs = [os.path.basename(x) for x in refs_out.splitlines() if x.strip()]
                            logger.info("    Referenced by: %s", ", ".join(refs) if refs else "(none)")
                        else:
                            logger.info("    Referenced by: (none)")
                    except Exception:
                        logger.info("    Referenced by: (query failed)")

            summary_info["deleted_count"] = total_deleted
            summary_info["failed_count"] = len(failed_paths)
            summary_info["referenced_count"] = len(referenced_paths)

            # Delete old build log files
            if logs_to_delete:
                logger.info("\nDeleting old build log files...")
                log_files_deleted = 0
                log_files_failed: List[str] = []
                for i, entry in enumerate(logs_to_delete, start=1):
                    log_file = entry["filename"]
                    log_path = project_path / "_rixpress" / log_file
                    logger.info("  [%d/%d] Deleting %s...", i, len(logs_to_delete), log_file)
                    if not log_path.exists():
                        logger.info("    [!] File not found (already deleted?)")
                        continue
                    try:
                        log_path.unlink()
                        if not log_path.exists():
                            log_files_deleted += 1
                            logger.info("    [OK] Successfully deleted")
                        else:
                            log_files_failed.append(log_file)
                            logger.info("    [X] Failed to delete (file still exists)")
                    except Exception as e:
                        log_files_failed.append(log_file)
                        logger.info("    [X] Error: %s", e)
                logger.info("\nBuild log deletion summary:")
                logger.info("  Successfully deleted: %d files", log_files_deleted)
                logger.info("  Failed: %d files", len(log_files_failed))
                if log_files_failed and verbose:
                    logger.info("\nFailed to delete log files:")
                    for lf in log_files_failed:
                        logger.info("  %s", lf)
                summary_info["log_files_deleted"] = log_files_deleted
                summary_info["log_files_failed"] = len(log_files_failed)

            logger.info("\nCleanup complete!")
            return summary_info
        finally:
            # Always attempt to remove created gcroot links and the temp dir
            if created_gcroot_links:
                for p in created_gcroot_links:
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception:
                        logger.debug("Failed to unlink gcroot link %s", p)
                # attempt to remove the parent temp directory if exists and empty
                if temp_gcroots_dir and temp_gcroots_dir.exists():
                    try:
                        shutil.rmtree(temp_gcroots_dir)
                    except Exception:
                        # ignore: best-effort cleanup
                        logger.debug("Failed to remove temp gcroots dir %s", temp_gcroots_dir)
    finally:
        # always release lock and restore signals
        try:
            if lock_path_context is not None:
                lock_path_context.release()
        except Exception:
            pass
        try:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
        except Exception:
            pass
