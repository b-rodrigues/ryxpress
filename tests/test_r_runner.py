import sys
from pathlib import Path

# Ensure the package in src/ is importable when running tests from the repo root
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests"
sys.path.insert(0, str(SRC))

from ryxpress.r_runner import rxp_make  # type: ignore


def test_rxp_make_real_pipeline_runs():
    """
    End-to-end test that runs the real gen-pipeline.R via Rscript and rxp_make.

    This test expects:
      - Rscript to be available on PATH,
      - the rixpress R package to be available in that R,
      - required Python packages (polars) available to the environment R/reticulate uses,
      - default.nix available in the same directory where the pipeline expects it.

    We run Rscript with cwd set to the src/ directory (where default.nix lives in your layout)
    so pipeline.nix can find ./default.nix.
    """
    repo_gen = SRC / "gen-pipeline.R"
    assert repo_gen.exists(), f"gen-pipeline.R not found at {repo_gen}"

    # Use src/ as the working directory so imports like ./default.nix resolve
    run_cwd = SRC

    result = rxp_make(
        script=str(repo_gen),
        verbose=0,
        max_jobs=1,
        cores=1,
        timeout=300,
        cwd=str(run_cwd),
    )

    # Helpful debugging output on failure
    if result.returncode != 0:
        print("===== rxp_make stdout =====")
        print(result.stdout)
        print("===== rxp_make stderr =====")
        print(result.stderr)

    assert result.returncode == 0, "rxp_make failed; see stdout/stderr above for details"
