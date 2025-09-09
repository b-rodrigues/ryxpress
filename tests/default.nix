let
 pkgs = import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2025-04-14.tar.gz") {};
 
  rpkgs = builtins.attrValues {
    inherit (pkgs.rPackages) 
      dplyr;
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

    rixpress = (pkgs.rPackages.buildRPackage {
      name = "rixpress";
      src = pkgs.fetchgit {
        url = "https://github.com/b-rodrigues/rixpress";
        rev = "HEAD";
        sha256 = "sha256-1zLzFXYtjAMNtYsAWnV778hK7EFeDOITVU0X7a6l0UQ=";
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
      polars;
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

    buildInputs = [ rix rixpress rpkgs pyconf system_packages ];
    
  }; 
in
  {
    inherit pkgs shell;
  }
