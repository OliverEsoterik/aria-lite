{
  description = "Alpha Picks";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
      
      # We create a postgres instance that includes the timescaledb extension
      postgresWithTimescale = pkgs.postgresql.withPackages (p: [ p.timescaledb ]);
      
      myPython = pkgs.python3.withPackages (p: with p; [
        pandas
        yfinance
        psycopg2
        sqlalchemy
        pandas-ta
        numpy
        requests
        hmmlearn
        scikit-learn
        pytest
      ]);
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          myPython
          postgresWithTimescale
        ];

        shellHook = ''
          export PROJECT_ROOT=$PWD
          export DB_PATH=$PWD/.db_data
          export PGHOST=$PWD/.db_data
          export PGPORT=5432
          export PGDATABASE=alphapicks

          echo "Environment ready."
          echo "Run 'make setup' for first-time database and ETL setup."
          echo "Run 'make run' for daily application start."
        '';
      };
    };
}