# AGENTS.md

Guidance for AI coding agents (and humans) working on this repository.

> **The test suite is part of every change.** Any change to behaviour (a new feature, a bug fix, a new
> endpoint, a new GUI function, a new MTL quirk, a new bundled dependency) comes with new or updated tests
> in `tests/` **in the same commit**. A change without tests is not finished. Run the whole suite before
> you say you're done: `python -m unittest discover -s tests`. See [The test suite](#the-test-suite).

## What this project is

`create-ivao-vmr` generates **vPilot model-matching rule files (`.vmr`)** for the
**IVAO MTL** (Multiplayer Traffic Library) installed in **Microsoft Flight Simulator 2020 or 2024**.
VATSIM pilots use vPilot. vPilot shows other pilots' aircraft in the sim using installed models, and
the VMR tells it which MTL livery to load for a given callsign and aircraft type.

- Upstream repository: **https://github.com/vojta48/create-ivao-vmr**. Pull requests go there.
  Forks (for example `DarrianCZE/create-ivao-vmr`) push branches and open PRs against `vojta48:main`.
- Originally written by andrewward2001. The AIG (Alpha India Group) mode is inherited from that version
  and still supported, but the IVAO MTL is the focus.
- vPilot docs: https://vpilot.rosscarlson.dev/Documentation · MTL: https://mtl.ivao.aero/
  (mtl.ivao.aero returns 403 to automated fetches; use an installed MTL as the reference instead).

## Repository layout

| Path | What it is |
| --- | --- |
| `create_vmr.py` | The command-line script. **Standalone, standard library only.** Users drop this single file into `Packages/Community/IVAO_MTL` and run it, so it must never import anything from this repo. It also holds the shared rule logic that the GUI imports. |
| `vmr_gui.py` | GUI backend: a local `ThreadingHTTPServer` (127.0.0.1) plus a pywebview window, or the browser when pywebview isn't installed. It imports its rule logic from `create_vmr.py`. |
| `gui/` | Static front end (`index.html`, `app.js`, `style.css`). Plain JS, no build step, no frameworks, no CDN. |
| `presets/` | Ready-made `.vmr` rule sets offered in the GUI. A `<!-- comment -->` in the file becomes its description. |
| `tests/` | The `unittest` suite (see [The test suite](#the-test-suite)). It builds a fake MTL in temp folders, so it needs no installed MTL. |
| `LICENSE`, `NOTICE` | Apache 2.0 (the unmodified text) and the copyright and attribution notice. |
| `tools/collect_licenses.py`, `tools/licenses/` | Generate `THIRD-PARTY-LICENSES.txt` for the release from the packages bundled into the exe. |
| `build_exe.spec` | PyInstaller spec for the portable `IVAO_VMR_Generator.exe`. It bundles `gui/`, `presets/` and `version.txt`, and writes the Windows version resource. Both versions come from the `APP_VERSION` environment variable (`0.0.0` if not set). |
| `.github/workflows/build-exe.yml` | CI: tests, then exe build, server and window smoke tests, and release on `v*` tags. |

Files the programs write at run time:
- the GUI (since 1.2), per Windows user, never next to the program (see "Where the program keeps its files" in `vmr_gui.py`):
  - `%APPDATA%\IVAO VMR Generator`: `settings.json` (see invariant 10), `my_rules.vmr` (the user's own rules, see
    invariant 11), and `presets/` for the user's own presets;
  - `%LOCALAPPDATA%\IVAO VMR Generator`: `vmr_gui.log` (exe only), `previews/` (catalog pictures);
  - `IVAO_VMR_GUI_DATA_DIR` puts all of them into one other folder. The tests set it in `support.py`, and the smoke tests set it in the workflow;
  - the exe's own folder, during an update only: `IVAO_VMR_Generator.exe.new` / `.part` (removed on failure) and `.old`
    (the previous exe, deleted at the next start);
- in the folder `create_vmr.py` is run from: `create_vmr.log`, plus the VMRs;
- CI only: `/licenses/` (the generated license files; `tools/licenses/` is source and is committed).

`.gitignore` still lists the 1.1 file names (`vmr_gui_settings.json`, `vmr_gui_my_rules.vmr`, `previews/`, logs), so
that old copies in a working tree are never committed.

## Domain knowledge you need

### How vPilot matches (this drives every design decision)
- A rule is `<ModelMatchRule CallsignPrefix="DLH" TypeCode="A320" ModelName="A320DLH//A320DLH2" />`.
  `ModelName` must equal a `title=` in an installed `aircraft.cfg`. If it lists several names separated
  by `//`, vPilot picks one **at random**.
- `CallsignPrefix` is a **starts-with** match on the callsign. A prefix that no callsign can start with
  (`@UN`, `ZZZ`, digits) never matches. A 2-letter prefix matches far too much (`RN` also catches `RNA123`).
  The only valid prefixes are 3-letter ICAO airline codes, or no prefix at all.
- Other attributes: `Callsign` (exact match) and `FlightNumberRange` (`"4439-4858"`).
- No `CallsignPrefix` makes it a **type-only rule**, which is the fallback for any airline of that type.
- vPilot makes **four passes**: prefix + exact type → prefix + *similar* type → type-only + exact type →
  type-only + similar type. Within a pass, the **first matching line wins**, so a later rule with the
  same conditions is never used. The order of the files only breaks ties within a pass.
- The order inside a generated VMR is therefore presets → user's own rules → MTL-generated rules.

### Where the IVAO MTL is installed
The MTL Installer puts it into `<packages>\Community\IVAO_MTL`. Each simulator writes `<packages>` into its `UserCfg.opt`
as `InstalledPackagesPath "D:\...\Packages"`, and `UserCfg.opt` is in a fixed place per simulator (`SIMULATORS` in `vmr_gui.py`):

| Simulator | `UserCfg.opt` |
| --- | --- |
| MSFS 2024 Steam | `%APPDATA%\Microsoft Flight Simulator 2024\UserCfg.opt` |
| MSFS 2024 Microsoft Store | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\UserCfg.opt` |
| MSFS 2020 Steam | `%APPDATA%\Microsoft Flight Simulator\UserCfg.opt` |
| MSFS 2020 Microsoft Store | `%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\UserCfg.opt` |

`InstalledPackagesPath` is usually the last line, without a line break after it. Don't rely on that: the pattern must
also match CRLF lines in the middle of the file. Users can have both simulators, each with or without the MTL.
The Documents folder is often moved into OneDrive or has a translated name (`Dokumenty`), so `documents_folder()` asks Windows for it.

### What the IVAO MTL looks like on disk
`Packages/Community/IVAO_MTL/`
- `SimObjects/Airplanes/IVAO_<model>/aircraft.cfg`: one `[fltsim.N]` section per livery, with:
  - `title="A320AAF"`: the MTL id, which is what goes into `ModelName`.
  - `texture="AAF"`: the texture folder suffix. It **contains typos** (`DAL` for Air Dolomiti, `EZE` for EasyJet), and its first three letters are only a fallback for the airline code.
  - `ui_type="A320"`: the ICAO type (first 4 characters).
  - `ui_variation="Aigle Azur (old) (AAF)"`: the catalog name. The **last `(XXX)` is the ICAO airline code**, and the groups before it describe special liveries.
- `SimObjects/Airplanes/IVAO_<model>/ivao.cfg`: its `icao_type_designator` is **unreliable** (`GLID` for an A330, `B190` for an F100). Do not use it.
- `texture.<X>/ivao.ini`: `mtl_version = 11636` is the catalog number of the livery, used for the preview picture.
- `texture.<X>/ivao.liv`: a copy of that livery's `[fltsim]` block.
- `mtl.dat`: one line per livery, `id,catalog name,0.0,0.0,catalogNumber`. The name can contain commas, so take the last field.
- `Doc8643.txt` (ICAO type table), `related.txt` (similar types), `layout.json`, `manifest.json`: MSFS/MTL files that this project doesn't use.
- Known MTL defects the code tolerates:
  - a `VERSION]` header missing its `[`: `create_vmr.py` repairs it **in the file**, while the GUI repairs it **in memory only**;
  - duplicated sections (hence `strict=False`);
  - files that are UTF-8 with a BOM, or cp1252.
- Special airline codes:
  - `default` texture or no texture: the plain model, which becomes a **type-only** rule.
  - Texture equal to the type (`HAR` for "AV-8 Harrier") with no catalog code: the plain model, **type-only**.
  - Type `ZZZZ` (blimp, balloon): **type-only**. The invisible dummy (texture `dummy`, "No Model (Invisible)")
    is **left out**, so vPilot never picks it at random.
  - A name with the airline code in an earlier bracket ("Emirates (UAE) (NBA)"): the earlier code that the
    texture starts with wins.
  - `ZZZ` (no airline) and `@xx` (military/government): **left out** of the VMR, unless the catalog name gives a real code such as `(USN)`. The GUI still lists them (`inVmr: false`).

## Invariants: do not break these

1. **The script and the GUI generate identical rules.** The logic lives once, in `create_vmr.py`:
   `mtl_airline_code`, `mtl_type_code`, `is_standard_livery`, `group_rules`, `xml_attr`.
   `vmr_gui.Library` must call these and must not reimplement them. `tests/test_parity.py` enforces this.
2. **`create_vmr.py` stays a single standalone file** that runs with any Python 3 standard library.
   The GUI may depend on `pywebview`. Nothing else may be added as a runtime dependency.
3. **`build_vmr` (Python) and `buildVmr` (`gui/app.js`) produce the same text.** "Save to output folder"
   uses the Python one, while the preview, "Save as" and the browser download use the JS one. Change both together.
4. **Importing a VMR must not make a rule broader.** Keep `Callsign` and `FlightNumberRange`
   (as `exactCallsign` / `flightNumbers`) through parse → GUI → build.
5. **The GUI never changes the MTL.** It never changes, repairs or deletes a file of the MTL. It writes VMR files only
   to the output folder, which by default is the `IVAO_MTL` folder root, where `create_vmr.py` writes its VMRs too. A new
   `.vmr` there is the only file it ever adds to the MTL. Its own files go only to its AppData folders (see above). The one
   exception is an update, which writes the new exe next to the running one.
6. **The local server answers only this computer.** It checks the Host header, POSTs must be `application/json`,
   and there is no endpoint that reads arbitrary paths. Keep it that way when you add endpoints. In particular:
   - The Community folder can only be changed to one `find_mtl_folders` found (`/api/community`), or one the user
     picked in the window's folder dialog (`JsApi.choose_community_folder`).
   - The output folder can only be changed through the folder or Save as dialogs; `/api/output-folder` only resets it.
   - `/api/settings` must not accept `communityFolder` (`PAGE_SETTINGS`).
   - Automatic lookup is the normal way to find the MTL. The Community folder the user picked is only an override, and
     *Find it automatically* (`/api/community` with `null`) clears it.
7. **The README privacy policy must stay true.** It is part of the SignPath Foundation code-signing
   requirements. If the program starts contacting a new host or sending new data, update the policy in the same PR.
8. Output files: UTF-8. GUI VMRs use CRLF. Escape every attribute value with `xml_attr`.
9. **Licensing.** The project is Apache 2.0 and derived from Andrew Ward's original, so the license cannot be
   changed. Don't edit the `LICENSE` text; copyright holders and attribution go in `NOTICE`. When the exe gets
   a new bundled dependency, add it to `PACKAGES` in `tools/collect_licenses.py`. The script fails the build
   when a license text is missing; put a copy into `tools/licenses/` if the wheel does not ship one.
10. **Settings stay compatible between versions.** `settings.json` (in `%APPDATA%\IVAO VMR Generator`; 1.1 used
    `vmr_gui_settings.json` next to the program) keeps the VMR name, the last save folder, the ticked presets, the MTL
    choice, the Community folder the user chose (`communityFolder`) and the update check. The rules for changing it (see the
    "Settings" section in `vmr_gui.py`):
    - **Adding a setting:** add it to `SETTINGS` with a default and a check function. **Don't** raise
      `SETTINGS_VERSION`: old files simply get the default.
    - Never rename a key or change the meaning or type of an existing one in place. Add a new key instead
      and leave the old one unused.
    - Only a change old files really cannot follow raises `SETTINGS_VERSION`. Raise
      `OLDEST_SUPPORTED_SETTINGS_VERSION` only when old files must be thrown away. Those files are then deleted
      at start, and the GUI tells the user once that the settings were from a version that is no longer
      supported and were reset. Both changes need a test in `tests/test_settings.py`.
    - Settings must never stop the program: invalid values fall back to their default one by one, unknown
      keys (also inside groups such as `mtlRules`) are kept on write, and a failed write is only logged.
    - `createdBy` / `savedBy` are the app version from `version.txt` (written by `build_exe.spec`, `dev` from
      source). They are information only; compatibility is decided by `settingsVersion`.
    - Tests use `Settings(None)` (in memory) or a temp folder, never the real file next to the program.
11. **The user's own rules are never lost by accident.** *My rules* live in `my_rules.vmr` in the data folder
    (`MyRules` in `vmr_gui.py`):
    - The files of 1.1 are copied to the data folder (`copy_old_files`). They are `vmr_gui_settings.json`,
      `vmr_gui_my_rules.vmr` and the user's own `presets/*.vmr`, next to the program and usually in `IVAO_MTL`.
      - They are looked for at start in the program folder, the current folder, `-d`, the MTL of the chosen Community
        folder and every MTL found.
      - When the user later chooses a Community folder, its MTL is checked too (`App.use_community`), and the settings
        and rules are read again.
      - Copy, never move.
      - Never replace a file of the user in the data folder. The only exception is a rules file without any rule: the
        page writes one at the first start, so it doesn't count.
      - Never copy a preset with the name of a bundled one. In a source checkout that would be an old copy of the
        bundled preset, which would hide the newer one.
    - The file is a plain VMR (`build_vmr` / `parse_vmr`), never JSON. That format doesn't change, so the
      file needs no version and is never deleted, not even when the settings are reset.
    - The page sends all its rules after every change (`/api/my-rules`). Only complete rules are stored.
    - At start (once per run), liveries that are no longer installed are removed from the rules, and rules
      left without a livery are removed; the GUI shows what was removed. **Nothing is removed when the MTL
      folder is missing, has no liveries, or the scan reported errors.** A wrong `-d` or a damaged
      `aircraft.cfg` must never wipe the user's rules. Keep these guards.
    - A user can have the MTL in MSFS 2020 and 2024, with different liveries. A livery is only missing when no MTL
      found on the computer has it (`App.checked_my_rules` reads the other MTLs). The same guards apply to every
      MTL: if one of them is broken, nothing is removed. Otherwise starting once with the other simulator would
      strip the rules.
    - Rules from the old browser storage (key `ivao-vmr-generator-draft`) are moved to the file when there
      is no file yet. Don't remove that migration while users of 1.0.x may still update.
12. **An update never leaves the user without a working program.** The updater (`Updater` in `vmr_gui.py`) only
    downloads `IVAO_VMR_Generator.exe` from a release of `vojta48/create-ivao-vmr` (`RELEASE_DOWNLOADS`). Before it
    touches the running exe, it checks the size and the SHA-256 `digest` GitHub publishes. It also checks the
    signature: when the running exe has a valid Authenticode signature with `CN=SignPath Foundation`, the new one
    must have it too. An unsigned exe (1.1.0 was released unsigned because SignPath wasn't set up yet) may only take an
    unsigned update that has a `digest`. It renames the running exe to `.old` (Windows allows renaming a running
    program, but not deleting it), and renames it back when putting the new one in place fails. The new exe is
    started with `PYINSTALLER_RESET_ENVIRONMENT=1`, otherwise it would reuse the old one's unpacked files.
    Development versions are never offered an update: `dev` (from source), `0.0.0` (every workflow build that isn't a
    release) and any version newer than the latest release (`development` in `Updater.status`). Development versions
    and the self-test mode never contact GitHub. The `checkForUpdates` setting switches off the check at start.
    The page offers a newer release in a prompt with *Update* and *Ignore*. *Update* installs at once and restarts,
    without a second question. *Ignore* lasts for the run. If you weaken any of these checks, the README privacy policy and the code
    signing policy are no longer true.

## The test suite

**Keep it up to date with every change. This is not optional.** The tests are the only thing that stops the
script and the GUI from drifting apart again, and the only check before a release goes out. When you
change behaviour, update the tests in the same commit:

- **New behaviour → new tests.** Bug fixes get a test that fails without the fix.
- **Changed behaviour → change the tests deliberately.** Don't weaken or delete an assertion just to get the
  suite green. If an expectation really changed (for example how a livery's airline code is chosen), update
  it and explain why in the commit message.
- **New MTL quirk found in a real installation → add it to the fake MTL** (`LIVERIES` in `tests/support.py`,
  with a comment), so that `test_parity.py` and `test_script.py` cover it from then on.
- **New endpoint, GUI function, preset, option or bundled package → extend the matching test file** (table below).
- **Never skip or disable tests to make CI pass.** The only allowed skips are the existing ones: no Node.js,
  no pywebview, no `IVAO_MTL_DIR`.

Run it:
- Everything: `python -m unittest discover -s tests` (Windows: `py -3 -m unittest discover -s tests`). Standard
  library only; it takes a few seconds. CI runs it before every build, and a failing test blocks the exe.
- One file: `python -m unittest discover -s tests -p test_server.py -v`. Don't use `-m unittest tests.x`,
  because `tests/` must be on the import path for `support.py`.
- Against a real MTL (read-only; the script runs on a copy):
  `IVAO_MTL_DIR=<...\Community\IVAO_MTL> python -m unittest discover -s tests -p test_real_mtl.py -v`.
  Run this after any change to the rule logic.
- The JavaScript tests run `gui/app.js` functions in Node.js (`node` on PATH). Install Node locally so they don't skip.

| File | Covers |
| --- | --- |
| `support.py` | Shared helpers, not tests: the fake MTL (`LIVERIES`, `make_mtl`, `write_model`), `run_script` (runs `create_vmr.main()` with fresh globals), `read_rules`, `ServerTestCase` (a real server on a free port). It sets `IVAO_VMR_GUI_DATA_DIR` to a temp folder **before** importing `vmr_gui`, so import `vmr_gui` only through `support`. |
| `test_rules.py` | The pure rule functions in `create_vmr.py`: `livery_name_parts`, `is_standard_livery` (every neutral qualifier), `mtl_airline_code`, `mtl_type_code`, `xml_attr`, `build_rule`, `group_rules`. |
| `test_script.py` | `create_vmr.py` as a program: `VERSION]` repair (bytes, BOM, CRLF, read-only files), reading aircraft.cfg (encodings, duplicates, broken files, skipped liveries, unquoted titles), output files and counts, every command line option, the AIG mode. |
| `test_parity.py` | Invariant 1: the script and the GUI produce identical rules and standard rules from the same MTL, leave out the same liveries, and handle its odd cases the same way. |
| `test_library.py` | `vmr_gui.Library`: livery fields, catalog numbers (`ivao.ini`, `mtl.dat`), reported problems, never changing the MTL. |
| `test_vmr_format.py` | `parse_vmr`/`build_vmr` (all attributes, regex fallback, escaping, round trip), `_read_text`, `list_presets`. |
| `test_previews.py` | Catalog pictures: download once, cache, failures remembered, parallel requests. The network is mocked; tests must never go online. |
| `test_server.py` | Every HTTP endpoint, saving files, path traversal, and invariant 6 (Host check, JSON-only POST, no file-reading endpoint). |
| `test_window.py` | The pywebview file dialogs (`JsApi`) and the fallback without pywebview, with a fake `webview` module. |
| `test_my_rules.py` | Invariant 11: the own-rules file round trip, cleaning up after MTL changes (and the guards that prevent it), several simulators with different MTLs, `/api/my-rules`, and the server self-test mode that stops by itself. |
| `test_settings.py` | Invariant 10: the settings file round trip, files from older (1.1), newer, unsupported and broken versions, the notice, the output folder from the last save, `/api/settings` (and that it can't set `communityFolder`), the Save as dialog, the app version. |
| `test_files.py` | The AppData folders (and that tests never use the real ones), the log, finding the MTL through `UserCfg.opt` for all four simulators, the order in which the MTL is chosen (`-d`, chosen Community folder, program folder, simulators), the output folder (the MTL, then `Documents\vPilot Files`), copying the 1.1 files and presets (also when a Community folder is chosen later), `/api/community`, `/api/output-folder`, the folder dialogs, the GUI without any MTL. |
| `test_update.py` | Invariant 12: versions, reading a GitHub release, the check (once, off, from source, offline), the install with every failure (unsigned, checksum, size, download, folder, swap) leaving the old exe untouched, the restart, `/api/update`. The Windows-only tests run the real signature check on system files. |
| `test_frontend.py` | `index.html` ↔ `app.js` ↔ server consistency, and the JS functions (`buildVmr` identical to `build_vmr`, invariant 3) run in Node.js. |
| `test_project.py` | Presets are valid and have no shadowed rules, license files and headers, `collect_licenses.py`, build spec, workflow (including smoke tests that never kill the exe), `.gitignore`, `create_vmr.py` stays standard-library only. |
| `test_real_mtl.py` | Optional checks against a real installation (`IVAO_MTL_DIR`). Skipped otherwise. |

Writing tests: use `unittest` and the standard library only (no pytest, no new dependencies). Use temp folders
(`TempDirTestCase`) and never the real MTL or the repo folder for output. Mock the network and pywebview. Keep the
plain, explanatory comment style of the rest of the code.

## Working on the code

- Run the tests (see above) before and after every change.
- Check the JS syntax: `node --check gui/app.js` (also part of `test_frontend.py`).
- Run the GUI from source: `python vmr_gui.py -d <IVAO_MTL folder> -p <output folder> [--browser | --no-browser] [--port N]`.
- **Testing against a real MTL:** `create_vmr.py` rewrites broken `aircraft.cfg` files in place. Never point it
  at someone's live MTL while experimenting. Copy `SimObjects/Airplanes/*/aircraft.cfg` (plus `mtl.dat`) to a
  scratch folder and run on the copy. `vmr_gui.Library(...).scan()` is read-only and safe on a live install.
  A useful check after rule changes: compare `create_vmr` output with `Library.mtl_rules()` on the copy, and
  diff the rule set against the previous `ivaomtl.vmr` to see what changed for users.
- Build the exe (Windows): `pip install pyinstaller pywebview`, then `pyinstaller build_exe.spec`, which gives `dist/IVAO_VMR_Generator.exe`.
  Set `APP_VERSION` first (for example `1.1.0-test`) to give a test build a recognisable version; otherwise it is `0.0.0`.
  Never commit `build/`, `dist/`, `previews/` or logs (see `.gitignore`).
- **Smoke-testing the exe locally:** it is a one-file PyInstaller exe, so it runs as a launcher process plus the
  real program. `Stop-Process` on the launcher leaves the program running, and it keeps its port and `vmr_gui.log`.
  Instead, set `IVAO_VMR_GUI_SELFTEST=1`:
  - with `--no-browser`, the server runs and the program ends by itself after 40 seconds (a watchdog);
  - without it, the window opens, loads the page and closes (exit code 0 when it worked).
  The workflow uses the same mode for both smoke tests (with `IVAO_VMR_GUI_SELFTEST_SECONDS` to shorten the
  server run) and checks that the exe ended by itself with exit code 0. Never go back to `Stop-Process`.

## Style

- Match the existing code. The comments are full sentences in plain English that explain *why*, often with
  a concrete MTL example (`texture="DAL"` for Air Dolomiti). Keep the comment density of the surrounding code.
- Python: standard library, `%`-formatting and string concatenation as in the surrounding code, no type hints,
  module-level globals in `create_vmr.py` (CLI style). New pure helpers there are fine and preferred.
- JS: one IIFE in `app.js`, the `el()` helper to build the DOM, `state` object, `api()` for server calls.
- User-facing text (README, GUI labels, console output) is plain, friendly English for flight simmers,
  not developers. Explain vPilot consequences ("this rule is never used because…").
- The working tree uses CRLF via `core.autocrlf`, and git stores LF. Don't create mixed line endings.

## Git and releases

- Branch from `main`. Never commit directly to `main`. Open PRs against `vojta48/create-ivao-vmr:main`.
  In a fork, add the upstream repository as a second remote (`git remote add upstream
  https://github.com/vojta48/create-ivao-vmr.git`) and fetch it before starting new work.
- Keep the first line of a commit message under 72 characters. GitHub uses it as the PR title and cuts
  longer ones. Write the PR description for the reviewer (why, what changed, effect on users, how it was
  tested) instead of relying on the commit message.
- CI must be green: the tests, the exe build, and both smoke tests (server and window).
- Every PR that changes behaviour includes the matching test changes. Reviewers should reject it otherwise.
- **Releases:**
  1. Merge the PR into `vojta48/create-ivao-vmr:main`.
  2. Push a tag `vX.Y.Z` on that commit. Only there: never tag a fork, because releases are published only
     from vojta48's repository.
  3. CI builds the exe with `APP_VERSION` from the tag, and the release gets the exe, `LICENSE`, `NOTICE` and
     `THIRD-PARTY-LICENSES.txt`. The exe is not code signed.
  4. Add the release notes, written for users rather than developers, to the GitHub release.
  Releases are never built on a developer machine. If the settings file format changes in a release, see
  invariant 10 and say so in the release notes.
