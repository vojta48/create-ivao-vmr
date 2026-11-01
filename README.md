# create-ivao-vmr
Create vPilot model matching rules (a `.vmr` file) for the [IVAO MTL](https://mtl.ivao.aero/) in Microsoft Flight Simulator 2020 and 2024, so that other pilots on VATSIM show up in the right aircraft and the right airline livery.

There are two ways to use it:

- **IVAO VMR Generator** (`IVAO_VMR_Generator.exe`, or `vmr_gui.py` from source): a window where you combine the rules generated from your MTL with ready-made presets and your own rules. You can see every livery with its picture, and you save one VMR for vPilot. Most users want this one.
- **`create_vmr.py`**: a script that writes the VMRs generated from your MTL with one command, without any window.

Both generate exactly the same rules from the MTL.

## Before you start
1. Install the IVAO MTL with the [MTL Installer](https://mtl.ivao.aero/installer). It goes into the `Community` folder of your simulator, for example:
   - MSFS 2024 (Steam): `...\steamapps\common\MSFS2024\Packages\Community\IVAO_MTL`
   - MSFS 2020 (Steam): `...\steamapps\common\MicrosoftFlightSimulator\Packages\Community\IVAO_MTL`
   - Microsoft Store versions: the `Community` folder inside the packages folder chosen when the sim was installed (`InstalledPackagesPath` in the sim's `UserCfg.opt`).

   The GUI finds this folder by itself (see [Which MTL is used](#which-mtl-is-used)); only `create_vmr.py` has to be put into it.
2. Install [vPilot](https://vpilot.rosscarlson.dev/) and make sure it finds your simulator.

## IVAO VMR Generator (GUI)

### Start it
**Portable .exe (no Python, no installation):** download `IVAO_VMR_Generator.exe` from the [releases](https://github.com/vojta48/create-ivao-vmr/releases), put it anywhere you like (the desktop, a folder of your tools) and double-click it. The program opens in its own window, using the Microsoft Edge WebView2 runtime that is part of Windows 10 and 11. The version is shown next to the title. Release builds are code signed (see [Code signing policy](#code-signing-policy)). A build you take from a workflow run under *Actions* is not signed, so Windows SmartScreen may warn about an unknown publisher; use such a file only if you trust where it came from.

**From source:** run `python vmr_gui.py` from the folder with `create_vmr.py`, `vmr_gui.py`, the `gui` folder and the `presets` folder (requires [Python](https://www.python.org/) 3). With `pip install pywebview` it opens in its own window; without it, it opens in your browser at http://127.0.0.1:8765.

### Which MTL is used
The program reads where your simulator keeps its packages from the simulator's `UserCfg.opt`, and looks for the `IVAO_MTL` folder in its `Community` folder. This works for MSFS 2020 and MSFS 2024, both the Steam and the Microsoft Store versions. The folder in use is shown in step 1, *Basic rules*.

Normally you don't have to do anything. For the cases where you do:
- If you have the MTL in more than one simulator, the first one found is used: MSFS 2024 before MSFS 2020, Steam before Microsoft Store. You can switch to the other one there.
- If the MTL is not found (for example because your `Community` folder is somewhere unusual), click *Choose the Community folder…* and pick the `Community` folder that contains `IVAO_MTL`. Picking the `IVAO_MTL` folder itself works too.
- The folder you choose is remembered. *Find it automatically* goes back to the automatic lookup.
- If you still keep the .exe in the `IVAO_MTL` folder, as version 1.1 needed, that MTL is used.
- On the command line, `-c <Community folder>` sets the Community folder and `-d <IVAO_MTL folder>` sets the MTL folder, each for one run.

### Build your VMR
While the program reads your MTL at start (a few seconds with thousands of liveries), a loading screen shows how far it is. The program is a wizard of three steps: **1 Basic rules** (the rules generated from your MTL), **2 Presets** and **3 My rules** (your own rules, the liveries of your MTL, and saving). *Continue* and *Back* move between the steps, and the three buttons at the top jump to any step directly. Every choice is kept while you move back and forth, and the button of each step shows what is chosen in it.

The VMR is put together from three parts, in this order. vPilot uses the first rule that fits, so the earlier parts win, and a later rule with the same callsign and type (a preset rule that the MTL rules repeat, for example) is left out of the file:

1. **Presets**: ready-made rule sets for cases the MTL does not cover. Tick the ones you want. They are shown as a tree of two groups side by side; ticking a group ticks all its presets, and each preset keeps its own checkbox:
   - **Airline groups** (files named `*_group.vmr`): the airlines of a group fly each other's aircraft or share a livery, so a callsign without a livery of its own gets the group's one: `smartwings_group` (Smartwings, Smartwings Poland/Hungary/Slovakia, Czech Airlines), `lufthansa_group`, `air_france_klm_group`, `iag_group`, `latam_group`, `sas_group`, `norwegian_group`, `ryanair_group`, `wizz_air_group`, `easyjet_group` and `tui_group`;
   - **Other presets**: `airBaltic_ACMI` (airBaltic A220s wet-leased to Brussels Airlines, Austrian, Lufthansa, Air Serbia and SAS) and `extra_rules` (liveries missing from the MTL, substituted with a similar one).

   Click a livery id in a preset's rules to see its picture in a window over the page; close it with its button, Escape or a click outside it.

   Every `.vmr` file in the `presets` folder is offered as a preset, and a `<!-- comment -->` in the file is shown as its description. Put your own presets into `%APPDATA%\IVAO VMR Generator\presets` (create the folder). A preset there replaces a built-in one with the same name. A `presets` folder next to the .exe, where version 1.1 read them, still works.
2. **My rules**: one line per rule.
   - **Callsign**: the 3-letter airline code. Leave it empty for any callsign.
   - **Type**: the ICAO aircraft type.
   - **Models**: the MTL livery ids. Separate several ids with `//`; vPilot then picks one at random.

   Click a livery in the list next to the rules to add it to the rule you are editing. You can also import the rules of an existing VMR file. Rules with vPilot's `Callsign` (one exact callsign) or `FlightNumberRange` attributes keep them. The GUI warns about liveries that are not installed, and about rules that vPilot would never use because a ticked preset or an earlier rule already has the same callsign and type.
3. **The rules generated from your MTL**: tick *Add the rules generated from my MTL* and choose *standard liveries only* or *all liveries* (see [How the MTL rules are generated](#how-the-mtl-rules-are-generated)).

Step 3 lists every livery installed in your MTL with its picture, catalog name, type and airline, and marks special liveries. Search by airline, type, id or name. The ↗ opens a livery in the [MTL catalog](https://mtl.ivao.aero/catalog). If some `aircraft.cfg` files of your MTL cannot be read, or contain liveries without a type, without a title or with a title another livery already uses, the GUI lists them in step 1 under the MTL rules. Those liveries are missing until you repair the MTL with the MTL Installer.

**Save** writes the file to the output folder, or anywhere through *Save as…*.
- The output folder is the `IVAO_MTL` folder, where `create_vmr.py` writes its VMRs too. Without an MTL it is `Documents\vPilot Files` (the folder vPilot keeps its own files in), or `Documents`.
- *Change…* next to the output folder picks another one. *Save as…* to another folder also makes that folder the output folder. *Use the IVAO_MTL folder* goes back.
- The output folder is remembered.
- The MTL Installer does not know about your VMR in the `IVAO_MTL` folder. If you ever reinstall the MTL from scratch, save the VMR again.

**Where the program keeps its files.** Nothing is written next to the program, so it can be started from any folder:
- `%APPDATA%\IVAO VMR Generator`: your settings (`settings.json`), your own rules (`my_rules.vmr`) and your own presets (`presets`).
- `%LOCALAPPDATA%\IVAO VMR Generator`: the log (`vmr_gui.log`) and the downloaded livery pictures (`previews`).

Type the path into the address bar of Windows Explorer to open the folder.

**Moving from version 1.1.** Version 1.1 kept your settings, your rules and your own presets next to the program, usually in the `IVAO_MTL` folder. Version 1.2 copies them into `%APPDATA%\IVAO VMR Generator` and says so.
- This happens at the first start, or when you choose the Community folder because the MTL was not found by itself.
- Built-in presets are not copied, because the program brings newer ones itself.
- Nothing of yours that is already there is replaced.
- The old files are left as they are, and you can delete them.

**Your settings are remembered.** The program keeps the name of the VMR, the output folder, the ticked presets, the MTL choice, the Community folder you chose and whether to check for updates in `settings.json`, and starts with them the next time. A new version of the program keeps using that file. The file records which version created it. Only when a version changes the file in a way the old file cannot follow is the old file deleted: the program then shows a message that the settings were from a version that is no longer supported and were reset to the defaults. A damaged settings file is handled the same way. You can delete the file at any time to start from the defaults.

**Your own rules are remembered too.** *My rules* are kept in `my_rules.vmr`, an ordinary VMR file that you can also open or import elsewhere. It is separate from the settings, so a settings reset never touches your rules. Rules you are still typing (no type or no livery yet) are not stored. Rules that older versions kept in the page's browser storage are moved into the file at the first start.

**When the IVAO MTL changes.** At every start the program compares your rules with the liveries that are installed.
- A livery that is no longer installed is removed from your rules, and a rule left without any livery is removed. The program then shows what it removed.
- If you have the MTL in both MSFS 2020 and 2024, a livery is only removed when neither MTL has it, so switching between the simulators never costs you rules.
- Nothing is removed when an MTL is not found, or when some of its `aircraft.cfg` files cannot be read, because then the liveries are probably only missing for the moment.

**Where the pictures come from.** The thumbnails inside the MTL packages are the same generic picture for every livery, so the GUI shows the pictures from the MTL catalog instead. It finds the catalog number of each livery in the `ivao.ini` that the MTL Installer writes into every texture folder, or in the installer's `mtl.dat`. That number is all the download needs: no IVAO account, no API key. Each picture is downloaded the first time it is shown and kept in the `previews` folder in `%LOCALAPPDATA%\IVAO VMR Generator`, so it works offline afterwards. You can delete that folder at any time.

**Updates.** At start the program asks GitHub whether there is a newer release. If there is, it asks you with *Update* and *Ignore*, and shows what's new.
- *Update* downloads the new `IVAO_VMR_Generator.exe` right away, puts it in place of the old one and restarts the program. Your settings and rules are kept.
- *Ignore* closes the question until the next start. *Check now* under *Program* asks again.
- A version newer than the latest release (a development build) is never offered an update. Neither are test builds (`0.0.0`) and the program run from source.
- The update is only installed when the file is complete and matches the checksum GitHub publishes for it. If the program you have is signed by SignPath Foundation, Windows must confirm the same signature on the new one; a signed program is never replaced by an unsigned one. If anything fails, the program you have stays as it is, and you can download the new version from the release page.
- If the .exe is in a folder Windows does not let you change (such as `Program Files`), download the new version yourself.
- To stop the check at start, untick *Check for a new version at start* under *Program*. *Check now* still asks GitHub when you click it.

### Options
`-c` the Community folder that contains `IVAO_MTL` · `-d` the `IVAO_MTL` folder itself (default for both: see [Which MTL is used](#which-mtl-is-used)) · `-p` the output folder (default: the folder you chose or saved to last, the first time the `IVAO_MTL` folder; `-p` overrides it for that run) · `--port` the port of the local server (a free one is used if it is taken) · `--browser` use the web browser instead of the window · `--no-browser` only run the server.

If the .exe runs into a problem, it shows a message and writes the details to `vmr_gui.log` in `%LOCALAPPDATA%\IVAO VMR Generator`.

## create_vmr.py (command line)
Put `create_vmr.py` into your `IVAO_MTL` folder, open a terminal there and run:
```
python create_vmr.py
```
It takes a few seconds and writes two files into the folder you run it from:

- `ivaomtl.vmr`: rules with every livery in the MTL.
- `ivaomtl_standard.vmr`: the same rules with only the standard livery of each airline (see below). Use **either** this file **or** `ivaomtl.vmr` in vPilot, not both.

At the end the script prints how many liveries it read, how many special liveries the standard VMR leaves out, and any `aircraft.cfg` files it had to repair or could not read. Everything it prints is also written to `create_vmr.log` in the same folder. Please attach that file when you report a problem.

### Options
| Option | Meaning |
| --- | --- |
| `-d`, `--directory <path>` | The `SimObjects/Airplanes` folder of the MTL (default: `./SimObjects/Airplanes`). Put the path in quotation marks. |
| `-p`, `--output-directory <path>` | Folder for all output files (default: the current folder), e.g. `-p "C:\Users\me\Documents\vPilot Files"`. |
| `-o`, `--output <file>` | Name of the VMR (default: `ivaomtl.vmr`). The standard-only VMR takes its name from it: `-o my.vmr` writes `my.vmr` and `my_standard.vmr`. |
| `-l`, `--library <ivao\|aig>` | `aig` builds `aig.vmr` from the [Alpha India Group](https://www.alpha-india.net/) AI traffic library instead (run it from the `aig-aitraffic-oci-beta` folder). The standard-only VMR exists for the IVAO MTL only. |
| `-v`, `--verbose` | Print every file, rule and special livery, and every livery left out of the VMR. |
| `-n`, `--no-pause` | Don't wait for Enter at the end (the pause keeps the window open when the script is double-clicked). |

## How the MTL rules are generated
The GUI and the script use the same rules:

- **One rule per airline and aircraft type**, with all its liveries as alternatives: `<ModelMatchRule CallsignPrefix="DLH" TypeCode="A320" ModelName="A320DLH//A320DLH2" />`.
- **Airline code.** vPilot uses a rule when the pilot's callsign starts with its `CallsignPrefix`, so the prefix has to be the ICAO airline code. It is taken from the catalog name of the livery (`Air Dolomiti (DLA)` gives `DLA`), because some texture names in the MTL contain typos: `texture="DAL"` for Air Dolomiti would show Air Dolomiti for Delta flights. Liveries without a code in their name use the first three letters of their texture.
- **The plain model of a type** gets a rule without a callsign, so that every aircraft of that type whose airline has no rule of its own still gets the right aircraft. These are the `default` livery, a livery without a texture, and a livery whose texture is the type itself (`HAR` for the AV-8 Harrier). The same goes for the type `ZZZZ` (blimp, balloon).
- **Left out:** liveries without a usable airline code. These are `ZZZ` (no airline: a mix of private and government aircraft) and `@xx` (military and government). No callsign starts with these codes, so their rules would never be used. Military liveries whose name carries a real code, such as `United States Navy (USN)`, are kept with that code. The MTL's invisible model (`No Model (Invisible)`) is left out too, because otherwise vPilot would sometimes pick it for `ZZZZ` aircraft and show nothing. The GUI still lists left-out liveries (marked *not in the MTL rules*), and you can use them in your own rules. `create_vmr.py -v` prints each one.
- **Standard liveries only.** The MTL has many special, retro, alliance and event liveries next to the normal one. vPilot picks one of the listed liveries at random, so an airline with one standard and three special liveries would mostly show up in a special one. The standard-only variant leaves the special liveries out.
  - The standard livery is recognised by its catalog name. `Air Canada (ACA)` is standard, while `Air Canada (old colors) (ACA)` and `Lufthansa (Star Alliance) (DLH)` are special.
  - Names that only mention engines, winglets or a new scheme (`(CFM)`, `(Sharklets)`, `(New Colors)`) still count as standard.
  - Without a name, the texture decides: `EWG` is standard, `EWG2` is special.
  - If an airline has only special liveries for a type, they are kept, because a special livery is still better than a generic aircraft.

## Using the VMR in vPilot
In vPilot open *Settings → Model Matching → Custom Rules* and add the file with *Add Custom Rule Set(s)*. After changing a file while vPilot is running, type `.reloadrules` in vPilot.

- A VMR from the GUI **with** the MTL rules replaces `ivaomtl.vmr`. Don't add both.
- A VMR from the GUI **without** the MTL rules goes **above** the MTL VMR, so that its rules win.

**How vPilot chooses.** For each aircraft vPilot looks through all rule files in up to four passes. It stops at the first rule that fits:
1. The airline and the exact type.
2. The airline and a similar type (for example a B733 for a B734).
3. A rule without an airline, with the exact type.
4. A rule without an airline, with a similar type.

Within a pass, files higher in the list win. If nothing fits, vPilot uses its own automatic matching or your default model.

**Several libraries.** If you also use other model sets, a sensible order is the specific ones first and broad substitution sets last. For example:
```
FSLTL
AIG (create_vmr.py -l aig)
IVAO MTL (this program)
British Avgeek's VMR
```
[British Avgeek's VMR](https://flightsim.to/file/23365/full-vatsim-aig-beta-model-matching) contains many substitutions, such as a FedEx B763 for a FedEx B722. Placed last, it only fills the gaps: a FedEx B722 is found in the IVAO MTL first and shown as a B722.

## Troubleshooting
**"VERSION]" errors.** Some `aircraft.cfg` files in the MTL contain the section header `VERSION]` instead of `[VERSION]`.
- `create_vmr.py` adds the missing `[` in the file and lists the files it fixed. Nothing else in the file is changed.
- The GUI reads these files without changing them.

If the script cannot write the fix (for example because the file is read-only), open the file it names, find the line `VERSION]` near the end and change it to `[VERSION]`.

**Liveries or a whole aircraft are missing.** If an `aircraft.cfg` cannot be read at all, the script lists it under *Some files had errors*, and the GUI shows it above the liveries. This usually means the MTL installation is damaged; repair or update it with the MTL Installer and run again.

**Anything else:** open an [issue](https://github.com/vojta48/create-ivao-vmr/issues) and attach `create_vmr.log` or `vmr_gui.log`.

## Development
- Tests: `python -m unittest discover -s tests` (standard library only, no MTL needed; the JavaScript tests also need Node.js). They cover the script, the GUI server and front end, and check that `create_vmr.py` and the GUI generate the same rules. The workflow runs them before every build. To also check against your installed MTL (read-only), set `IVAO_MTL_DIR` to its folder and run `python -m unittest discover -s tests -p test_real_mtl.py -v`. Every change has to come with matching tests; see [AGENTS.md](AGENTS.md#the-test-suite).
- Build the .exe on Windows: `pip install pyinstaller pywebview`, then `pyinstaller build_exe.spec`. The result is `dist/IVAO_VMR_Generator.exe`. It shows the version `0.0.0` unless you set it first, for example `$env:APP_VERSION = "1.1.0-test"` in PowerShell. Running from source shows `dev` and never checks for updates.
- `IVAO_VMR_GUI_DATA_DIR=<folder>` makes the GUI keep all its files in that folder instead of AppData. The tests and the smoke tests of the workflow use it, so that they never touch your real settings and rules.
- The GitHub Actions workflow `build-exe.yml` runs the tests, builds the exe and smoke tests it for every pull request and every push to `main`. For a `v*` tag it also has the exe signed and attaches it to the release together with `LICENSE`, `NOTICE` and `THIRD-PARTY-LICENSES.txt`. The version comes from the tag (`v1.1.0` gives `1.1.0`).
- Notes for contributors and AI coding agents are in [AGENTS.md](AGENTS.md).

## License
Licensed under the [Apache License 2.0](LICENSE). The original `create_vmr.py` was written by [Andrew Ward (andrewward2001)](https://github.com/andrewward2001/create-ivao-vmr). This project is a modified and extended version of it; see [NOTICE](NOTICE) for the copyright holders.

The .exe also contains third-party software under its own licenses: Python, pywebview and its dependencies, the Microsoft WebView2 SDK and the PyInstaller bootloader, all under permissive licenses. Their copyright notices and license texts are in `THIRD-PARTY-LICENSES.txt`, which is attached to every release next to `LICENSE` and `NOTICE`. The build generates it from the bundled packages with `tools/collect_licenses.py`.

This project is not affiliated with or endorsed by IVAO, VATSIM, the author of vPilot or Microsoft. The livery pictures come from the IVAO MTL catalog at run time and are not part of this project.

## Privacy
The program runs entirely on your computer. It does not collect, store or send any personal data, usage statistics or crash reports. The only internet connection it makes is to download the pictures of the liveries it shows from the MTL catalog (`download.ivao.aero`); the request contains nothing but the catalog number of the livery. Each picture is downloaded once and kept in the `previews` folder next to the program. Your settings and your own rules are kept in `vmr_gui_settings.json` and `vmr_gui_my_rules.vmr` next to the program and never leave your computer. Clicking a livery link opens `mtl.ivao.aero` in your browser. Both are covered by [IVAO's privacy policy](https://ivao.aero/privacy). `create_vmr.py` makes no internet connection at all. The local server of the GUI only accepts connections from your own computer.

The Windows executable `IVAO_VMR_Generator.exe` attached to a [release](https://github.com/vojta48/create-ivao-vmr/releases) is digitally signed, so that Windows can verify who published the file and that it was not changed after the build. To check the signature, open the file's *Properties → Digital Signatures* in Windows Explorer, or run `Get-AuthenticodeSignature IVAO_VMR_Generator.exe` in PowerShell. The signer is *SignPath Foundation*. An executable that is not signed (a workflow artifact of a pull request, or a build you made yourself) should only be used if you built it or trust where it came from.

**How a release is built and signed.** Every release is built by [GitHub Actions](https://github.com/vojta48/create-ivao-vmr/actions/workflows/build-exe.yml) from the source code of this repository (`build-exe.yml` and `build_exe.spec`), never on a developer's computer. SignPath verifies that the executable comes from this repository's build, and the signing request is then approved by hand by an approver listed below. Every signing request requires this manual approval. The private key is kept in SignPath's hardware security module; nobody involved in the project has it.

**Team roles.** Changes from anyone outside the team are reviewed before they are merged.

| Role | Members |
| --- | --- |
| Committers and reviewers | [vojta48](https://github.com/vojta48), [DarrianCZE](https://github.com/DarrianCZE) |
| Approvers | [vojta48](https://github.com/vojta48) |

**Privacy policy.** The program runs entirely on your computer. It does not collect, store or send any personal data, usage statistics or crash reports. It makes only these internet connections:
- It downloads the pictures of the liveries it shows from the MTL catalog (`download.ivao.aero`). The request contains nothing but the catalog number of the livery. Each picture is downloaded once and kept in the `previews` folder in `%LOCALAPPDATA%\IVAO VMR Generator`. Clicking a livery link opens `mtl.ivao.aero` in your browser. Both are covered by [IVAO's privacy policy](https://ivao.aero/privacy).
- At start it asks GitHub (`api.github.com`) for the latest release of the program. The request contains nothing but the version of the program you have. When you click *Update*, it downloads the new program from the release on `github.com`, which GitHub serves from its download servers. Both are covered by [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement). To switch the check off, untick *Check for a new version at start*; GitHub is then only asked when you click *Check now*.

Your settings and your own rules are kept in `%APPDATA%\IVAO VMR Generator` and never leave your computer. `create_vmr.py` makes no internet connection at all. The local server of the GUI only accepts connections from your own computer.

**Reporting a problem.** If you think a signed release contains something it should not, do not run it and open an [issue](https://github.com/vojta48/create-ivao-vmr/issues) with the file's SHA256 hash and where you downloaded it.
