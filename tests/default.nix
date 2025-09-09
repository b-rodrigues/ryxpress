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
        rev = "HEAD";
        sha256 = "sha256-8ApbYTBqkyuB44bx2DXHqHNhbV3oZBul5TetuZLMNXw=";
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
        sha256 = "sha256-C5tF54mbQsZYCCI7RGWfdO13VAQcjvnp0IXMjqtv0E8=";
      };
      propagatedBuildInputs = builtins.attrValues {
        inherit (pkgs.rPackages) 
          igraph
          jsonlite
          processx;
      };
    });
   
  pyconf = builtins.attrValues {
    inherit (pkgs.python312Packages) 
      pip
      ipykernel
      polars;
  };
   
  system_packages = builtins.attrValues {
    inherit (pkgs) 
      glibcLocales
      nix
      python312
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
    RETICULATE_PYTHON = "${pkgs.python312}/bin/python";

    buildInputs = [ rix rixpress rpkgs pyconf system_packages ];
    
  }; 
in
  {
    inherit pkgs shell;
  }
