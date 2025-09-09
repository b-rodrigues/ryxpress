import sys
from pathlib import Path

# Ensure the package in src/ is importable when running tests from the repo root
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ryxpress.r_runner import rxp_make  # type: ignore


def test_rxp_make_real_pipeline_runs():
    """
    End-to-end test that runs the real gen-pipeline.R via Rscript and rxp_make.

    This test expects:
      - Rscript to be available on PATH,
      - the rixpress R package to be installable/available in that R,
      - any Python packages your pipeline uses (e.g. polars) to be available
        in the environment that R/reticulate will use (ensure your nix-shell
        provides them).

    The test invokes rxp_make with the real script located at src/test/gen-pipeline.R
    and asserts the command exits successfully (return code 0). On failure the
    captured stdout/stderr are available to help debug.
    """
    repo_gen = ROOT / "tests" / "gen-pipeline.R"
    assert repo_gen.exists(), f"gen-pipeline.R not found at {repo_gen}"

    # Call rxp_make using the real Rscript from PATH (default rscript_cmd)
    result = rxp_make(
        script=str(repo_gen),
        verbose=0,
        max_jobs=1,
        cores=1,
        # do not override rscript_cmd so the real Rscript in the environment is used
    )

    # Helpful debugging output on failure
    if result.returncode != 0:
        print("===== rxp_make stdout =====")
        print(result.stdout)
        print("===== rxp_make stderr =====")
        print(result.stderr)

    assert result.returncode == 0, "rxp_make failed; see stdout/stderr above for details"
