let
 pkgs = import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2026-01-19.tar.gz") {};
 
  rpkgs = builtins.attrValues {
    inherit (pkgs.rPackages) 
      dplyr;
  };
 
    rix = (pkgs.rPackages.buildRPackage {
      name = "rix";
      src = pkgs.fetchgit {
        url = "https://github.com/ropensci/rix/";
        rev = "792852bfeb9e7cc71f8759c01ea8a882779c7fad";
        sha256 = "sha256-TI4WpJkySo1+d7c0agv1QrbeWDUCD3lmxoer0JZ1yBg=";
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
        url = "https://github.com/ropensci/rixpress";
        rev = "28eace8e30675497bbf195ced670e82d4a10098c";
        sha256 = "sha256-P2wNbFwx/7pb3JZCG26jd5sjN8qp8YaVHxMIEZV9MiM=";
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
      polars
      pytest;
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
