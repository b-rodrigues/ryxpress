let
 pkgs = import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2025-08-18.tar.gz") {};
 
  pypkgs = builtins.attrValues {
    inherit (pkgs.python313Packages) 
      ipython
      polars
      mkdocs
      mkdocs-material
      mkdocstrings-python
      mkdocs-git-revision-date-localized-plugin
      pytest;
  };

    rix = (pkgs.rPackages.buildRPackage {
      name = "rix";
      src = pkgs.fetchgit {
        url = "https://github.com/ropensci/rix/";
        rev = "0da8ea99512af940ab2dce0153ea2f1ed5cd3883";
        sha256 = "sha256-5KUi4HBmZNl8rL5KqFV4fwPEwB6AZULisbdxHPWts8U=";
      };
      propagatedBuildInputs = builtins.attrValues {
        inherit (pkgs.rPackages) 
          codetools
          curl
          jsonlite
          sys;
      };
    });

  rpkgs = builtins.attrValues {
    inherit (pkgs.rPackages) 
      dplyr
      ;
  };

    rixpress = (pkgs.rPackages.buildRPackage {
      name = "rixpress";
      src = pkgs.fetchgit {
        url = "https://github.com/b-rodrigues/rixpress/";
        rev = "56a4864e48999c4255f6cdcf0fbd52111e1c4059";
        sha256 = "sha256-1zLzFXYtjAMNtYsAWnV778hK7EFeDOITVU0X7a6l0UQ=";
      };
      propagatedBuildInputs = builtins.attrValues {
        inherit (pkgs.rPackages) 
          igraph
          jsonlite
          processx;
      };
    });

  tex = (pkgs.texlive.combine {
    inherit (pkgs.texlive) 
      scheme-small
      inconsolata;
  });
  
  system_packages = builtins.attrValues {
    inherit (pkgs) 
      pyright
      ispell
      glibcLocales
      glibcLocalesUtf8
      nix
      pandoc
      python313
      R;
  };
  
in

pkgs.mkShell {
  LOCALE_ARCHIVE = if pkgs.system == "x86_64-linux" then "${pkgs.glibcLocales}/lib/locale/locale-archive" else "";
  LANG = "en_US.UTF-8";
   LC_ALL = "en_US.UTF-8";
   LC_TIME = "en_US.UTF-8";
   LC_MONETARY = "en_US.UTF-8";
   LC_PAPER = "en_US.UTF-8";
   LC_MEASUREMENT = "en_US.UTF-8";
   RETICULATE_PYTHON = "${pkgs.python313}/bin/python";

  buildInputs = [ rix rixpress rpkgs pypkgs tex system_packages ];

  shellHook = ''
    export PYTHONPATH=$PWD/src:$PYTHONPATH
  '';
  
}
