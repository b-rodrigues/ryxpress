from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass
class RRunResult:
    returncode: int
    stdout: str
    stderr: str

    def __str__(self):
        return (
            f"RRunResult(\n"
            f"  returncode={self.returncode},\n"
            f"  stdout=\n{self.stdout}\n"
            f"  stderr=\n{self.stderr}\n"
            f")"
        )

    def __repr__(self):
        # Used for "result" in REPL or IPython
        return self.__str__()


def rxp_make(
    script: Union[str, Path] = "gen-pipeline.R",
    verbose: int = 0,
    max_jobs: int = 1,
    cores: int = 1,
    rscript_cmd: str = "Rscript",
    timeout: Optional[int] = None,
    cwd: Optional[Union[str, Path]] = None,
) -> RRunResult:
    """
    rxp_make

    Run the rixpress R pipeline (rxp_populate + rxp_make) by sourcing an R script.

    Parameters:

    - script: Path or name of the R script to run (defaults to "gen-pipeline.R").
              If a relative path is given and doesn't exist in the working directory,
              this function will attempt to locate the script on PATH.
    - verbose: integer passed to rixpress::rxp_make(verbose = ...)
    - max_jobs: integer passed to rixpress::rxp_make(max_jobs = ...)
    - cores: integer passed to rixpress::rxp_make(cores = ...)
    - rscript_cmd: the Rscript binary to use (defaults to "Rscript")
    - timeout: optional timeout in seconds for the subprocess.run call
    - cwd: optional working directory to run Rscript in. If None, the directory
           containing the provided script will be used. This is important because
           pipeline.nix and related files are often imported with relative paths
           (e.g. ./default.nix), so Rscript needs to be run where those files are reachable.

    Returns an RRunResult containing returncode, stdout, stderr.
    """
    # Validate integers
    for name, val in (("verbose", verbose), ("max_jobs", max_jobs), ("cores", cores)):
        if not isinstance(val, int):
            raise TypeError(f"{name} must be an int, got {type(val).__name__}")
        if val < 0:
            raise ValueError(f"{name} must be >= 0")

    # Resolve script path: prefer given path if it exists; otherwise try to find on PATH
    script_path = Path(script)
    if not script_path.is_file():
        # If a bare name was provided, attempt to find it on PATH
        found = shutil.which(str(script))
        if found:
            script_path = Path(found)
        else:
            raise FileNotFoundError(
                f"R script '{script}' not found in working directory and not on PATH"
            )
    else:
        script_path = script_path.resolve()

    # Determine working directory for the R process:
    if cwd is not None:
        run_cwd = Path(cwd).resolve()
        if not run_cwd.is_dir():
            raise FileNotFoundError(f"Requested cwd '{cwd}' does not exist or is not a directory")
    else:
        # default to the script's parent directory so relative imports (./default.nix) work
        run_cwd = script_path.parent

    # Verify Rscript binary exists
    if shutil.which(rscript_cmd) is None:
        raise FileNotFoundError(
            f"Rscript binary '{rscript_cmd}' not found in PATH. Ensure R is installed or adjust rscript_cmd."
        )

    # Prepare wrapper R script that:
    #  - loads rixpress,
    #  - sources the user's script,
    #  - if the sourced evaluation returns a list, calls rxp_populate on it,
    #  - then calls rixpress::rxp_make(...) with the provided args.
    wrapper = f"""
suppressPackageStartupMessages(library(rixpress))

script_path <- "{script_path.as_posix()}"

if (!file.exists(script_path)) {{
  stop("Script not found: ", script_path)
}}

result_value <- NULL

res <- tryCatch({{
  # Source & evaluate the user's script and capture the returned value (if any)
  result_value <- eval(parse(script_path))
  # If the script returned a list (a pipeline), run rxp_populate on it
  if (!is.null(result_value) && is.list(result_value)) {{
    pipeline <- result_value
    pipeline <- rixpress::rxp_populate(pipeline)
  }}
  # Finally, run rxp_make with the given integer parameters
  rixpress::rxp_make(
    verbose = {int(verbose)},
    max_jobs = {int(max_jobs)},
    cores = {int(cores)}
  )
}}, error = function(e) {{
  # Print a clear error message and exit with non-zero status
  message("rixpress-python-runner-error: ", conditionMessage(e))
  quit(status = 1)
}})

# If we reach here, exit with success
quit(status = 0)
"""

    # Create temporary file for wrapper
    with tempfile.NamedTemporaryFile(mode="w", suffix=".R", delete=False) as tf:
        tf.write(wrapper)
        wrapper_path = Path(tf.name)

    try:
        # Run Rscript on the wrapper file using the desired working directory
        proc = subprocess.run(
            [rscript_cmd, str(wrapper_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=str(run_cwd),
        )
        return RRunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    finally:
        try:
            wrapper_path.unlink()
        except Exception:
            pass
