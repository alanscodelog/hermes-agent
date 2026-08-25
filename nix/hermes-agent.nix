# nix/hermes-agent.nix — Overridable Hermes Agent package
#
# callPackage auto-wires nixpkgs args; flake inputs are passed explicitly.
# Users override via:
#   pkgs.hermes-agent.override { extraPythonPackages = [...]; }
#   pkgs.hermes-agent.override { extraDependencyGroups = [ "hindsight" ]; }
{
  lib,
  stdenv,
  makeWrapper,
  fetchurl,
  callPackage,
  python312,
  electron,
  ripgrep,
  git,
  openssh,
  ffmpeg,
  tirith,

  # linux-only deps
  wl-clipboard,
  xclip,

  # linux-only dev deps
  cage,

  # Flake inputs — passed explicitly by packages.nix and overlays.nix
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  npm-lockfile-fix,
  # Locked git revision of the flake source — embedded so banner.py can
  # check for updates without needing a local .git directory. Null for
  # impure / dirty builds where flakes can't determine a rev.
  rev ? null,
  # Overridable parameters
  extraPythonPackages ? [ ],
  extraDependencyGroups ? [ ],
}:
let
  mkHermesVenv =
    extraDependencyGroups:
    callPackage ./python.nix {
      inherit uv2nix pyproject-nix pyproject-build-systems;
      pythonSrc = hermesNpmLib.pythonSrc;
      dependency-groups = [ "all" ] ++ extraDependencyGroups;
    };

  hermesVenv = (mkHermesVenv extraDependencyGroups).venv;

  hermesNpmLib = callPackage ./lib.nix {
    inherit npm-lockfile-fix;
  };

  hermesTui = callPackage ./tui.nix {
    inherit hermesNpmLib;
  };

  hermesWeb = callPackage ./web.nix {
    inherit hermesNpmLib;
  };

  bundledSkills = lib.cleanSourceWith {
    src = ../skills;
    filter = path: _type: !(lib.hasInfix "/index-cache/" path) && !(lib.hasInfix "/__pycache__/" path);
  };

  # Optional skills are NOT in the wheel (pythonSrc excludes them, see
  # lib.nix) — the wrapper exposes them via HERMES_OPTIONAL_SKILLS, the
  # same mechanism Homebrew packaging uses.
  bundledOptionalSkills = lib.cleanSourceWith {
    src = ../optional-skills;
    filter = path: _type: !(lib.hasInfix "/index-cache/" path) && !(lib.hasInfix "/__pycache__/" path);
  };

  # Import bundled plugins (memory, context_engine, platforms/*).  Keeping
  # them out of the Python site-packages keeps import semantics identical
  # to a dev checkout — the loader reads them from HERMES_BUNDLED_PLUGINS.
  bundledPlugins = lib.cleanSourceWith {
    src = ../plugins;
    filter = path: _type: !(lib.hasInfix "/__pycache__/" path);
  };

  # i18n locale catalogs (locales/*.yaml). Shipped into the store and pointed
  # at by HERMES_BUNDLED_LOCALES so the wrapped binary always resolves human
  # strings instead of raw i18n keys (#23943 / #27632 / #35374).
  bundledLocales = lib.cleanSource ../locales;

  # Shipped MCP catalog (optional-mcps/<name>/manifest.yaml). Same bare-data-dir
  # case as locales: not a Python package, so it's symlinked into the store and
  # exposed via HERMES_OPTIONAL_MCPS.
  bundledOptionalMcps = lib.cleanSourceWith {
    src = ../optional-mcps;
    filter = path: _type: !(lib.hasInfix "/__pycache__/" path);
  };

  # openWakeWord's shared feature models (melspectrogram + embedding, onnx and
  # tflite variants). Upstream ships them only as release assets — the pip
  # package has no resources/models/ and openwakeword.utils.download_models()
  # writes into the INSTALLED package dir, which is read-only in the Nix store.
  # Fetch them at build time (pinned by sha256) and expose the dir via
  # HERMES_WAKE_WORD_MODELS; tools/wake_word.py passes the paths straight into
  # Model() and skips the write. Same bare-data-dir pattern as locales.
  bundledWakeModels = stdenv.mkDerivation {
    name = "openwakeword-feature-models";
    dontUnpack = true;
    srcs = [
      (fetchurl {
        url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.tflite";
        sha256 = "96fa0adccb6e8cf95cb14465409a1a2898ee4a96a85bb9ed3c7eb0e68bf163e8";
        name = "melspectrogram.tflite";
      })
      (fetchurl {
        url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.tflite";
        sha256 = "c0aea21eb84a4ce90a08c870da41b7a7173b45269e6a3207c71d67c40f3a59d8";
        name = "embedding_model.tflite";
      })
      (fetchurl {
        url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx";
        sha256 = "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f";
        name = "melspectrogram.onnx";
      })
      (fetchurl {
        url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx";
        sha256 = "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f";
        name = "embedding_model.onnx";
      })
    ];
    installPhase = ''
      mkdir -p $out
      for f in $srcs; do
        # Store paths are <32-char-hash>-<name>; strip the hash so the file
        # lands as its bare name (melspectrogram.onnx, etc.) — openwakeword
        # looks for the bare name inside HERMES_WAKE_WORD_MODELS.
        cp "$f" "$out/$(basename "$f" | sed 's/^[a-z0-9]\{32\}-//')"
      done
    '';
  };

  runtimeDeps = [
    hermesNpmLib.nodejs
    ripgrep
    git
    openssh
    ffmpeg
    tirith
  ]
  ++ lib.optionals stdenv.isLinux [
    wl-clipboard
    xclip
  ];

  runtimePath = lib.makeBinPath runtimeDeps;

  sitePackagesPath = python312.sitePackages;

  # Walk propagatedBuildInputs to include transitive Python deps in PYTHONPATH.
  # Without this, a plugin listing e.g. requests as a dep would fail at runtime
  # if requests isn't already in the sealed uv2nix venv.
  allExtraPythonPackages = python312.pkgs.requiredPythonModules extraPythonPackages;

  pythonPath = lib.makeSearchPath sitePackagesPath allExtraPythonPackages;

  checkPackageCollisions = ''
    import pathlib, sys, re

    def canonical(name):
        return re.sub(r'[-_.]+', '-', name).lower()

    # Collect core venv package names
    core = set()
    venv_sp = pathlib.Path('${hermesVenv}/${sitePackagesPath}')
    for di in venv_sp.glob('*.dist-info'):
        meta = di / 'METADATA'
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    core.add(canonical(line.split(':', 1)[1].strip()))
                    break

    # Check each extra package for collisions
    extras_dirs = [${lib.concatMapStringsSep ", " (p: "'${toString p}'") allExtraPythonPackages}]
    for edir in extras_dirs:
        sp = pathlib.Path(edir) / '${sitePackagesPath}'
        if not sp.exists():
            continue
        for di in sp.glob('*.dist-info'):
            meta = di / 'METADATA'
            if not meta.exists():
                continue
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    pkg = canonical(line.split(':', 1)[1].strip())
                    if pkg in core:
                        print(f'ERROR: plugin package \"{pkg}\" collides with a package in hermes sealed venv', file=sys.stderr)
                        print(f'  from: {di}', file=sys.stderr)
                        print(f'  Remove this dependency from extraPythonPackages.', file=sys.stderr)
                        sys.exit(1)
                    break

    print('No collisions found.')
  '';
in
stdenv.mkDerivation (finalAttrs: {
  pname = "hermes-agent";
  version = (fromTOML (builtins.readFile ../pyproject.toml)).project.version;

  dontUnpack = true;
  dontBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    # Symlinks, not copies: these are all store paths already, and the
    # wrapper env vars just hold paths.  Symlinking keeps this derivation
    # near-instant when only the venv changed, with an identical closure.
    mkdir -p $out/share/hermes-agent $out/bin
    ln -s ${bundledSkills} $out/share/hermes-agent/skills
    ln -s ${bundledOptionalSkills} $out/share/hermes-agent/optional-skills
    ln -s ${bundledPlugins} $out/share/hermes-agent/plugins
    ln -s ${bundledLocales} $out/share/hermes-agent/locales
    ln -s ${bundledOptionalMcps} $out/share/hermes-agent/optional-mcps
    ln -s ${hermesWeb} $out/share/hermes-agent/web_dist
    ln -s ${hermesTui}/lib/hermes-tui $out/ui-tui

    ${lib.concatMapStringsSep "\n"
      (name: ''
        makeWrapper ${hermesVenv}/bin/${name} $out/bin/${name} \
          --suffix PATH : "${runtimePath}" \
          --set HERMES_BUNDLED_SKILLS $out/share/hermes-agent/skills \
          --set HERMES_OPTIONAL_SKILLS $out/share/hermes-agent/optional-skills \
          --set HERMES_BUNDLED_PLUGINS $out/share/hermes-agent/plugins \
          --set HERMES_BUNDLED_LOCALES $out/share/hermes-agent/locales \
          --set HERMES_OPTIONAL_MCPS $out/share/hermes-agent/optional-mcps \
          --set HERMES_WEB_DIST $out/share/hermes-agent/web_dist \
          --set HERMES_TUI_DIR $out/ui-tui \
          --set-default HERMES_BIN $out/bin/hermes \
          --set HERMES_PYTHON ${hermesVenv}/bin/python3 \
          --set HERMES_NODE ${lib.getExe hermesNpmLib.nodejs} \
          --set HERMES_WAKE_WORD_MODELS ${bundledWakeModels}${
            # Fold the line continuation INTO the optionalString: a bare
            # `\` on the line above an empty expansion would dangle onto a
            # blank line, ending the makeWrapper command early and running
            # the next flag as its own shell command (`--suffix: command
            # not found`). Only reproduces when rev == null (dirty trees).
            lib.optionalString (rev != null) " \\\n          --set HERMES_REVISION ${rev}"
          }${
            lib.optionalString (
              extraPythonPackages != [ ]
            ) " \\\n          --suffix PYTHONPATH : \"${pythonPath}\""
          }
      '')
      [
        "hermes"
        "hermes-agent"
        "hermes-acp"
      ]
    }

    ${lib.optionalString (extraPythonPackages != [ ]) ''
      echo "=== Checking for plugin/core package collisions ==="
      ${hermesVenv}/bin/python3 -c "${checkPackageCollisions}"
      echo "=== No collisions ==="
    ''}

    runHook postInstall
  '';

  passthru =
    let
      devPython = (mkHermesVenv (extraDependencyGroups ++ [ "dev" ])).editableVenv;
    in
    {
      inherit
        hermesTui
        hermesWeb
        hermesNpmLib
        hermesVenv
        ;

      # `hermesDesktop` references `finalAttrs.finalPackage` (this whole
      # derivation, after all overrides are applied) so the desktop wrapper
      # can prepend its `/bin` to PATH.  The desktop's resolver step 4
      # ("existing hermes on PATH") then picks up the fully wrapped
      # `hermes` binary — venv with all deps, bundled skills/plugins,
      # runtime PATH (ripgrep/git/ffmpeg/etc).  No re-implementation
      # of the agent resolution in the desktop wrapper.
      hermesDesktop = callPackage ./desktop.nix {
        inherit hermesNpmLib electron;
        hermesAgent = finalAttrs.finalPackage;
      };

      devShellHook = ''
        export HERMES_PYTHON=${devPython}/bin/python3
      '';

      devDeps =
        runtimeDeps
        ++ [
          devPython
        ]
        ++ lib.optionals stdenv.isLinux [
          cage # for running e2e tests without popping windows
        ];
    };

  meta = with lib; {
    description = "AI agent with advanced tool-calling capabilities";
    homepage = "https://github.com/NousResearch/hermes-agent";
    mainProgram = "hermes";
    license = licenses.mit;
    platforms = platforms.unix;
  };
})
