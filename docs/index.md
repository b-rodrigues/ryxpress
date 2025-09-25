# ryxpress — Reproducible Analytical Pipelines with Nix (Python)

[![PyPI version](https://img.shields.io/pypi/v/ryxpress)](https://pypi.org/project/ryxpress/)

If you’re looking for `{rixpress}`, the R package version [look here](https://github.com/b-rodrigues/rixpress).

`ryxpress` is a Python reimplementation/port of the R package `{rixpress}`. It
provides helpers and a small framework to build and work with reproducible,
polyglot analytical pipelines that are built with Nix.

The goal is to define a pipeline using the following R code:

```r
library(rixpress)
library(igraph)

list(
  rxp_py_file(
    name = mtcars_pl,
    path = 'data/mtcars.csv',
    read_function = "lambda x: polars.read_csv(x, separator='|')"
  ),

  rxp_py(
    # reticulate doesn't support polars DFs yet, so need to convert
    # first to pandas DF
    name = mtcars_pl_am,
    expr = "mtcars_pl.filter(polars.col('am') == 1).to_pandas()"
  ),

  rxp_py2r(
    name = mtcars_am,
    expr = mtcars_pl_am
  ),

  rxp_r(
    name = mtcars_head,
    expr = my_head(mtcars_am),
    user_functions = "functions.R"
  ),

  rxp_r2py(
    name = mtcars_head_py,
    expr = mtcars_head
  ),

  rxp_py(
    name = mtcars_tail_py,
    expr = 'mtcars_head_py.tail()'
  ),

  rxp_py2r(
    name = mtcars_tail,
    expr = mtcars_tail_py
  ),

  rxp_r(
    name = mtcars_mpg,
    expr = dplyr::select(mtcars_tail, mpg)
  ),

  rxp_qmd(
    name = page,
    qmd_file = "my_doc/page.qmd",
    additional_files = c("my_doc/content.qmd", "my_doc/images")
  )
) |>
  rxp_populate(project_path = ".", build = TRUE)
```

`ryxpress` will execute an R session and call `{rixpress}` transparently to
build this pipeline in a completely reproducible way. Exploring the build
artifacts can then be done from an interactive Python session.

If you previously used the R version (`{rixpress}`), `ryxpress` aims to provide a
similar user experience for Python projects while integrating with the same
Nix-first workflow.

[Video introduction (original R demo)](https://www.youtube.com/watch?v=a1eNG9TFZ_o)

## Quick overview

- Use Nix to describe reproducible runtime/build environments.
- Define pipeline derivations (build steps) in your project using R syntax, but
  inspect and load artifacts using Python.
- Build pipelines with Nix and use ryxpress helpers to read, load or copy
  outputs from the Nix store.

## Installation

`ryxpress` is on Pypi and can be installed using any of the usual package managers.
That being said, since `ryxpress` requires both Nix and R to be available to
function, we provide instructions for Nix only.

### Prerequisites
- Nix installed on your machine. See the Nix project docs or Determinate Systems' installer.

Because `ryxpress` is a wrapper around the R version, both R and `{rixpress}` need to be available,
and since there’s not much point in using `ryxpress` if you don’t have Nix installed, the easiest
way to install it is to build the environment as defined by this `default.nix`:

```nix
let
 pkgs = import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2025-09-11.tar.gz") {};

 rixpress = (pkgs.rPackages.buildRPackage {
   name = "rixpress";
   src = pkgs.fetchgit {
     url = "https://github.com/b-rodrigues/rixpress";
     rev = "9a5dd6c31be9e6d413529924dd0816a510335881";
     sha256 = "sha256-iQRo42RSnJ1C/ySCRyuaDt2MTP9G6g52wm+kkSHCir0=";
   };
   propagatedBuildInputs = builtins.attrValues {
     inherit (pkgs.rPackages)
       igraph
       jsonlite
       processx;
   };
 });

  pyconf = builtins.attrValues {
    inherit (pkgs.python313Packages)
      pip
      ipykernel
      biocframe
      pandas
      rds2py
      ryxpress;
  };

  system_packages = builtins.attrValues {
    inherit (pkgs)
      glibcLocales
      nix
      python313
      R;
  };

  shell = pkgs.mkShell {
    LOCALE_ARCHIVE = if pkgs.system == "x86_64-linux" then "${pkgs.glibcLocales}/lib/locale/locale-archive" else "";
    LANG = "en_US.UTF-8";
    LC_ALL = "en_US.UTF-8";
    LC_TIME = "en_US.UTF-8";
    LC_MONETARY = "en_US.UTF-8";
    LC_PAPER = "en_US.UTF-8";
    LC_MEASUREMENT = "en_US.UTF-8";
    RETICULATE_PYTHON = "${pkgs.python313}/bin/python";

    buildInputs = [ rixpress pyconf system_packages ];

  };
in
  {
    inherit pkgs shell;
  }
```

You can change the date at the top to a more recent date to benefit from fresher packages.
If you plan to use `uv` to manage Python packages, remove the `pyconf` block completely, and
replace `python313` with `uv` in the `system_packages` block.

## Basic usage examples

Create a pipeline as an R script:

```r
library(rixpress)

list(
  rxp_py_file(
    name = dataset_np, # Keep name indicating NumPy array
    path = "data/pima-indians-diabetes.csv",
    read_function = "lambda x: loadtxt(x, delimiter=',')"
  ),

  rxp_py(
    name = X,
    expr = "dataset_np[:,0:8]"
  ),

  rxp_py(
    name = Y,
    expr = "dataset_np[:,8]"
  ),

  rxp_py(
    name = splits,
    expr = "train_test_split(X, Y, test_size=0.33, random_state=7)"
  ),

  # Extract X_train (index 0)
  rxp_py(
    name = X_train,
    expr = "splits[0]"
  ),

  # Extract X_test (index 1)
  rxp_py(
    name = X_test,
    expr = "splits[1]"
  ),

  # Extract y_train (index 2)
  rxp_py(
    name = y_train,
    expr = "splits[2]"
  ),

  # Extract y_test (index 3)
  rxp_py(
    name = y_test,
    expr = "splits[3]"
  ),

  rxp_py(
    name = model,
    expr = "XGBClassifier(use_label_encoder=False, eval_metric='logloss').fit(X_train, y_train)"
  ),

  rxp_py(
    name = y_pred,
    expr = "model.predict(X_test)"
  ),

  # Combine the y_test and y_pred vectors to export to csv
  # This will be done used in an R environment by yardstick::conf_mat
  rxp_py(
    name = combined_df,
    expr = "DataFrame({'truth': y_test, 'estimate': y_pred})"
  ),

  rxp_py(
    name = combined_csv,
    expr = "combined_df",
    user_functions = "functions.py",
    encoder = "write_to_csv"
  ),

  # yardstick::conf_mat needs factor variables
  rxp_r(
    combined_factor,
    expr = mutate(
      combined_csv,
      across(.cols = everything(), .fns = factor)
    ),
    decoder = "read.csv"
  ),

  rxp_r(
    name = confusion_matrix,
    expr = conf_mat(
      combined_factor,
      truth,
      estimate
    )
  ),

  rxp_py(
    name = accuracy,
    expr = "accuracy_score(y_test, y_pred)"
  )
) |>
  rxp_populate(build = FALSE) # Need to set to FALSE because we
# adjust imports first

adjust_import(
  "import numpy",
  "from numpy import array, loadtxt"
)

adjust_import("import xgboost", "from xgboost import XGBClassifier")

adjust_import(
  "import sklearn",
  "from sklearn.model_selection import train_test_split"
)

add_import("from sklearn.metrics import accuracy_score", "default.nix")
add_import("from pandas import DataFrame", "default.nix")
```

Start a Python session and:

```py
from ryxpress import rxp_make

rxp_make()
```

This will build the pipeline.

## Note on formats:

- `rxp_read`/`rxp_load` will try `pickle.load` first
- If pickle fails `rxp_read`/`rxp_load` will attempt to use the optional rds2py
  package (if present) to parse the file. This will load serialized R objects.
- If neither loader succeeds, the function returns the path(s).

## Inspect builds and outputs
- `rxp_inspect` inspects the project build logs and helps resolve derivation outputs.
- `rxp_copy` copies artifacts from `/nix/store` into your working directory for inspection.
- `rxp_gc` helps manage cache/cleanup of local artifacts.

## Docs and API reference (developer docs)
This repository uses MkDocs + mkdocstrings to generate documentation and an autogenerated API reference from the package docstrings.

## Contributing

Contributions are welcome. When contributing, please:
- Provide small, focused, and runnable examples.
- Prefer small datasets and short-running examples for `tests/docs`.
- Document any system-level dependencies for examples in a `default.nix` so the pipeline can be reproduced.

If you are unsure about a change, open an issue to discuss before submitting a
PR. See `CONTRIBUTING.md` for guidelines (if present).

## Scope

The Python port focuses on the same “micropipeline” use case: single-machine
pipelines for small-to-medium projects where Nix provides reproducible builds.
It aims to mirror the user experience of the R package where practical, but it
is not a drop-in replacement for all R-specific workflows. See the docs for
current feature coverage and examples.

## Examples & demos

See the examples and demos in the companion repository:
https://github.com/b-rodrigues/rixpress_demos

## License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See LICENSE for details.
