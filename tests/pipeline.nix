let
  default = import ./default.nix;
  defaultPkgs = default.pkgs;
  defaultShell = default.shell;
  defaultBuildInputs = defaultShell.buildInputs;
  defaultConfigurePhase = ''
    cp ${./_rixpress/default_libraries.py} libraries.py
    cp ${./_rixpress/default_libraries.R} libraries.R
    mkdir -p $out  
    mkdir -p .julia_depot  
    export JULIA_DEPOT_PATH=$PWD/.julia_depot  
    export HOME_PATH=$PWD
  '';
  
  # Function to create R derivations
  makeRDerivation = { name, buildInputs, configurePhase, buildPhase, src ? null }:
    defaultPkgs.stdenv.mkDerivation {
      inherit name src;
      dontUnpack = true;
      inherit buildInputs configurePhase buildPhase;
      installPhase = ''
        cp ${name} $out/
      '';
    };
  # Function to create Python derivations
  makePyDerivation = { name, buildInputs, configurePhase, buildPhase, src ? null }:
    let
      pickleFile = "${name}";
    in
      defaultPkgs.stdenv.mkDerivation {
        inherit name src;
        dontUnpack = true;
        buildInputs = buildInputs;
        inherit configurePhase buildPhase;
        installPhase = ''
          cp ${pickleFile} $out
        '';
      };

  # Define all derivations
    mtcars_pl = makePyDerivation {
    name = "mtcars_pl";
    src = defaultPkgs.fetchurl {
      url = "https://raw.githubusercontent.com/b-rodrigues/rixpress_demos/refs/heads/master/basic_r/data/mtcars.csv";
      sha256 = "1m8fwb871n6wqs62iis6kjaj12ymg586vq3cbny5i75bk0nddm2z";
    };
    buildInputs = defaultBuildInputs;
    configurePhase = defaultConfigurePhase;
    buildPhase = ''
      cp -r $src mtcars.csv
python -c "
exec(open('libraries.py').read())
file_path = 'mtcars.csv'
data = eval('lambda x: polars.read_csv(x, separator=\'|\')')(file_path)
with open('mtcars_pl', 'wb') as f:
    pickle.dump(data, f)
"
    '';
  };

  mtcars_pl_am = makePyDerivation {
    name = "mtcars_pl_am";
     src = defaultPkgs.lib.fileset.toSource {
      root = ./.;
      fileset = defaultPkgs.lib.fileset.unions [ ./functions.py ];
    };
    buildInputs = defaultBuildInputs;
    configurePhase = defaultConfigurePhase;
    buildPhase = ''
      cp ${./functions.py} functions.py
      python -c "
exec(open('libraries.py').read())
with open('${mtcars_pl}/mtcars_pl', 'rb') as f: mtcars_pl = pickle.load(f)
exec(open('functions.py').read())
exec('mtcars_pl_am = mtcars_pl.filter(polars.col(\'am\') == 1)')
serialize_to_json(globals()['mtcars_pl_am'], 'mtcars_pl_am')
"
    '';
  };

  mtcars_head = makeRDerivation {
    name = "mtcars_head";
     src = defaultPkgs.lib.fileset.toSource {
      root = ./.;
      fileset = defaultPkgs.lib.fileset.unions [ ./functions.R ];
    };
    buildInputs = defaultBuildInputs;
    configurePhase = defaultConfigurePhase;
    buildPhase = ''
      cp ${./functions.R} functions.R
      Rscript -e "
        source('libraries.R')
        mtcars_pl_am <- jsonlite::fromJSON('${mtcars_pl_am}/mtcars_pl_am')
        source('functions.R')
        mtcars_head <- my_head(mtcars_pl_am)
        saveRDS(mtcars_head, 'mtcars_head')"
    '';
  };

  mtcars_mpg = makeRDerivation {
    name = "mtcars_mpg";
    buildInputs = defaultBuildInputs;
    configurePhase = defaultConfigurePhase;
    buildPhase = ''
      Rscript -e "
        source('libraries.R')
        mtcars_head <- readRDS('${mtcars_head}/mtcars_head')
        mtcars_mpg <- dplyr::select(mtcars_head, mpg)
        saveRDS(mtcars_mpg, 'mtcars_mpg')"
    '';
  };

  # Generic default target that builds all derivations
  allDerivations = defaultPkgs.symlinkJoin {
    name = "all-derivations";
    paths = with builtins; attrValues { inherit mtcars_pl mtcars_pl_am mtcars_head mtcars_mpg; };
  };

in
{
  inherit mtcars_pl mtcars_pl_am mtcars_head mtcars_mpg;
  default = allDerivations;
}
