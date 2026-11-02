# This script creates a VMR file from the IVAO MTL model matching library.
# Run this script from the root folder of the MTL library "Packages/Community/IVAO_MTL"
# The output file is titled "ivaomtl.vmr" and is placed in this directory.
# Script by github.com/andrewward2001
# Changed and extended by the create-ivao-vmr contributors (https://github.com/vojta48/create-ivao-vmr).
# Licensed under the Apache License, Version 2.0; see the LICENSE and NOTICE files.

import configparser
import getopt
import os
import re
from pathlib import Path
import sys
import traceback
from collections import defaultdict

verbose = False
models_directory = "./SimObjects/Airplanes"
# All files are written to the folder the script is run from (the MTL folder), unless -p says otherwise.
output_directory = Path(".")
output_file = "ivaomtl.vmr"
log_file = "create_vmr.log"
lib = "ivao"
pause_at_end = True
# For the IVAO library the script writes two files next to each other in output_directory:
#   <output_file>            the complete VMR with every livery
#   <stem>_standard.vmr      the VMR with the standard airline liveries only
# excluded_types = ["A4", "B1", "B2", "BE12", "BE35", "BE36", "BE40", "BE60", "C152", "C172", "C207"]

errored_files = []
fixed_files = []
special_titles = set()
# Every livery read from the MTL: livery_info[title] = (airline code or None, type, texture, name, standard)
livery_info = {}
special_skipped = 0
special_kept = 0
model_list_len = 0
texture_len = 0
airlines_len = 0
rules_len = 0
no_code_len = 0

# Everything printed to the console is also written to the log file, so the output can be read
# even when the script is started by double-clicking it and the window closes right away.
class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

# The command line part (log file, options) runs only when the script is started directly.
# vmr_gui.py imports this file to reuse the livery rules below without running anything.
def parse_command_line():
    global verbose, models_directory, output_directory, output_file, lib, pause_at_end
    try:
        log = open(log_file, "w", encoding="utf-8")
        sys.stdout = Tee(sys.__stdout__, log)
        sys.stderr = Tee(sys.__stderr__, log)
        print("Log file: " + os.path.abspath(log_file))
    except OSError as err:
        print("Could not create log file " + log_file + ": " + str(err))

    argsList = sys.argv[1:]
    options = "d:o:vl:p:n"
    long_options = ['directory=', 'output=', 'verbose', 'library=', 'output-directory=', 'no-pause']

    try:
        arguments, values = getopt.getopt(argsList, options, long_options)

        for currentArgument, currentValue in arguments:
            if currentArgument in ("-d", "--directory"):
                models_directory = currentValue
                print("Reading from " + currentValue)
            elif currentArgument in ("-l", "--library"):
                if currentValue == "ivao":
                    lib = "ivao"
                elif currentValue == "aig":
                    lib = "aig"
                    output_file = "aig.vmr"
                else:
                    print("Error! Library can only be either \"ivao\" or \"aig\"")
                    exit()
            elif currentArgument in ("-o", "--output"):
                output_file = currentValue
            elif currentArgument in ("-v", "--verbose"):
                verbose = True
            elif currentArgument in ("-p", "--output-directory"):
                output_directory = Path(currentValue)
            elif currentArgument in ("-n", "--no-pause"):
                pause_at_end = False

        print("Output to: " + os.path.abspath(output_directory / output_file))
    except getopt.error as err:
        print(err)

# Creates the string that will be output on each new line of the VMR to act as a Rule.
# callsign: String referring to the 3-letter ICAO identifier used in a callsign (ex. AAL, DAL, UAL, BAW, etc.)
# type: String referring to the ICAO aircraft type identifier (ex. B738, A320, B77W)
# modeltitle: String referring to which model vPilot should load. This string must match the "title" entry under [fltsim.n] in the aircraft.cfg file
def build_rule(callsign, type, modeltitle):
    # <ModelMatchRule CallsignPrefix="BAW" TypeCode="B733" ModelName="F1UT2_733.BA.BA" />
    out = "<ModelMatchRule"

    # If the callsign is blank, "def" (default), or ZZZZ, then the rule isn't associated with an airline. By leaving out the "CallsignPrefix" vPilot will only match against the aircraft type and not the callsign.
    # The if statement is written this way because I am bad at python and this is the only way I could get it to work.
    if callsign == "" or callsign == "def" or type == "ZZZZ":
        # do nothing
        out = out + ""
    else:
        out = out + " CallsignPrefix=\"" + xml_attr(callsign) + "\""
    out = out + " TypeCode=\"" + xml_attr(type) + "\" ModelName=\"" + xml_attr(modeltitle) + "\" /> \n"
    return out

# Escapes a value for an XML attribute, so that a title with "&" or a quote still gives a valid VMR.
def xml_attr(value):
    return value.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;")

# Ensures that callsign entries are 3-letter airline identifiers. Otherwise, leave this blank.
# For the IVAO MTL it returns None when the livery has no airline code a callsign can start with (see mtl_airline_code).
def determine_callsign_prefix(entry):
    global lib
    if lib == "aig":
        try:
            return entry["icao_airline"].strip().strip("\"").strip()
        except:
            return ""
    if lib == "ivao":
        return mtl_airline_code(entry.get("texture", ""), entry.get("ui_variation", ""), mtl_type_code(entry.get("ui_type", "")))

# The CallsignPrefix of an IVAO MTL livery. vPilot uses a rule when the callsign starts with its CallsignPrefix.
#   ""    no prefix: a type-only rule. Used for the plain model of a type (texture="default" or no texture),
#         so that every aircraft of that type without an airline rule of its own gets it, and for the type ZZZZ
#         (no type designator: the MTL has a blimp, a balloon and an invisible model for it).
#   "ABC" the ICAO airline code. It is taken from the catalog name in ui_variation ("Air Dolomiti (DLA)"), because
#         the texture names contain typos (texture="DAL" for Air Dolomiti, "EZE" for EasyJet). Liveries without a
#         code in their name fall back to the first three letters of the texture.
#   None  no usable code: ZZZ (no airline, a mix of private and government aircraft), "@xx" (military and
#         government), numbers or a texture shorter than three letters. No callsign starts with these, so the
#         rule would never match; the livery is left out of the VMR (-v prints each one).
AIRLINE_CODE = re.compile(r"[A-Z]{3}")
NO_AIRLINE = "ZZZ"

#   A few names have the airline code in an earlier bracket and a livery tag last ("Emirates (UAE) (NBA)"): when
#   the texture starts with one of the earlier codes, that one is the airline. Liveries named after the plain
#   model with the type as texture (texture="HAR" for "AV-8 Harrier" of type HAR) get a type-only rule as well.
#   The MTL also has an invisible model (texture="dummy", "No Model (Invisible)"). It is left out as well: in the
#   type-only ZZZZ rule vPilot would pick it at random and show some aircraft as nothing at all.
#   The plain model is not always called "default": the MTL also names its textures "white" or "blank"
#   (texture="white" for "Cessna Caravan", texture="BLANK" for "General Aviation (Blank)"), and some plain models
#   have the texture ZZZ with a generic catalog name ("Default", "White", "White (Blank)", "General Aviation").
#   All of these are the plain model of their type and get the type-only rule; without it, "white" and "blank"
#   would become the callsigns WHI and BLA (Blue Air!), and the ZZZ ones would be left out, so an SR22 without an
#   airline rule would show nothing although the MTL has a default SR22.
INVISIBLE_TEXTURE = "dummy"
PLAIN_TEXTURES = ("", "default", "white", "blank")
PLAIN_NAMES = ("default", "white", "blank", "general aviation")
PLAIN_QUALIFIERS = ("white", "blank")

def is_plain_model_name(ui_variation):
    """True for a catalog name that only says the livery is the plain model: "Default", "White (Blank)",
    "General Aviation (Blank)". A name with an airline code is never one."""
    base, qualifiers, code = livery_name_parts(ui_variation)
    return code == "" and base.lower() in PLAIN_NAMES and all(q.strip().lower() in PLAIN_QUALIFIERS for q in qualifiers)

def mtl_airline_code(texture_name, ui_variation, type_code=""):
    texture = texture_name.strip().strip("\"")
    if texture.lower() == INVISIBLE_TEXTURE:
        return None
    if texture.lower() in PLAIN_TEXTURES or type_code == "ZZZZ" or is_plain_model_name(ui_variation):
        return ""
    base, qualifiers, code = livery_name_parts(ui_variation)
    prefix = texture[:3].upper()
    if code != prefix and prefix in qualifiers and AIRLINE_CODE.fullmatch(prefix) and prefix != NO_AIRLINE:
        code = prefix
    if not AIRLINE_CODE.fullmatch(code) or code == NO_AIRLINE:
        if type_code and texture.upper() == type_code:
            return ""
        code = prefix
    if not AIRLINE_CODE.fullmatch(code) or code == NO_AIRLINE:
        return None
    return code

# The aircraft type of an IVAO MTL livery: the first four characters of ui_type ("A320", "B38M", "F14").
def mtl_type_code(ui_type):
    return ui_type.strip().strip("\"")[:4].strip().upper()

# Groups the liveries into rules: one rule per airline and aircraft type with all its liveries as alternatives.
# model_list[airline][type] is the list of liveries (MTL ids) in the order they were found; special is the set of
# special liveries (see is_standard_livery). With standard_only the special liveries are left out, unless an
# airline has nothing but special liveries for a type: a special livery is still a better match than a generic one.
# Returns a list of (airline, type, liveries, kept) where kept is True when special liveries were kept for that reason.
# vmr_gui.py uses the same function, so the GUI and the script always generate the same rules.
def group_rules(model_list, special, standard_only):
    rules = []
    for airline in model_list:
        for type in model_list[airline]:
            variants = model_list[airline][type]
            kept = False
            if standard_only:
                standard_variants = [v for v in variants if v not in special]
                if len(standard_variants) > 0:
                    variants = standard_variants
                else:
                    kept = True
            rules.append((airline, type, variants, kept))
    return rules

# Decides whether a livery is the standard airline livery or a special / alternative one.
#
# The IVAO MTL puts the livery name from the MTL catalog into ui_variation, in the form
#   ui_variation="Air Canada (ACA)"                  -> the standard livery
#   ui_variation="Air Canada (old colors) (ACA)"     -> an alternative livery
#   ui_variation="Lufthansa (Star Alliance) (DLH)"   -> an alternative livery
# The last group in brackets is the airline code; every group before it describes what is special about the livery.
# A livery without such a group is the standard livery. A few descriptions do not make a livery special: they only
# say which engines or winglets the model has, or that it is the airline's new scheme. Those are listed below.
#
# If there is no ui_variation (older packages), the texture name decides instead: in the catalog the standard
# livery has no number (A320EWG = Eurowings, A320EWG2 = Eurowings Europa Park), and the texture name in the
# aircraft.cfg follows the same convention (texture="EWG" vs texture="EWG2").
NEUTRAL_QUALIFIERS = re.compile(
    r"^(cfm|iae|pw|p&w|pratt ?& ?whitney|rr|rolls[ -]?royce|ge|trent|leap|neo|ceo)( engines?)?$"
    r"|^(nc|new( colou?rs| livery| scheme)?|current( colou?rs| livery)?)$"
    r"|^(wl|(blended |split |scimitar )?winglets|sharklets)$"
)

def livery_name_parts(ui_variation):
    name = ui_variation.strip().strip("\"")
    groups = re.findall(r"\(([^()]*)\)", name)
    base = re.sub(r"\s*\([^()]*\)", "", name).strip()
    airline = ""
    if len(groups) > 0 and re.fullmatch(r"[A-Z0-9]{3}", groups[-1].strip()):
        airline = groups.pop().strip()
    return base, [g.strip() for g in groups], airline

def is_standard_livery(texture_name, ui_variation):
    if ui_variation.strip().strip("\"") != "":
        base, qualifiers, airline = livery_name_parts(ui_variation)
        return all(NEUTRAL_QUALIFIERS.match(q.lower()) for q in qualifiers)
    name = texture_name.strip().strip("\"")
    return re.search(r"[0-9]", name) is None

# Depending on if we are creating a VMR from the IVAO MTL or the AIG models, the aircraft type is located at a different part of the aircraft.cfg.
def determine_aircraft_type(config, section):
    global lib
    if lib == "aig":
        for mSection in config.sections():
            try:
                if "general" in mSection:
                    return config["general"]["icao_type_designator"][1:-1]
                elif "General" in mSection:
                    return config["General"]["icao_type_designator"][1:-1]
                elif "GENERAL" in mSection:
                    return config["GENERAL"]["icao_type_designator"][1:-1]
            except:
                return ""
        return ""
    else:
        return mtl_type_code(config[section]["ui_type"])
    

# Some IVAO MTL aircraft.cfg files ship with a broken section header "VERSION]" (missing the opening "[").
# configparser refuses to parse such a file, so the whole model would be left out of the VMR.
# This function fixes only that one problem: lines that read "VERSION]" are rewritten as "[VERSION]".
# The file is handled as raw bytes so the encoding, line endings and every other line stay exactly as they were.
# Returns True if the file was changed.
BROKEN_VERSION_LINE = re.compile(rb"^([ \t]*)VERSION\](?=[ \t]*(\r\n|\r|\n|$))")

def fix_version_section(file_to_read):
    try:
        with open(file_to_read, "rb") as f:
            lines = f.read().splitlines(keepends=True)
    except OSError:
        return False

    changed = False
    for i, line in enumerate(lines):
        new_line, count = BROKEN_VERSION_LINE.subn(rb"\1[VERSION]", line, count=1)
        if count:
            lines[i] = new_line
            changed = True
            if verbose: print("  Fixed 'VERSION]' -> '[VERSION]' on line " + str(i + 1) + " of " + file_to_read)

    if changed:
        try:
            with open(file_to_read, "wb") as f:
                f.writelines(lines)
            fixed_files.append(file_to_read)
        except OSError as err:
            print("Could not write fix to " + file_to_read + ": " + str(err))
            return False
    return changed

# Reads all the aircraft.cfg files from the directory models_directory.
# Assemble all the aircraft.cfg entries into a dictionary with format: model_list[CallsignPrefix][TypeCode][ModelName]
def create_model_list():
    model_list = defaultdict(dict)
    titles_seen = set()

    # sorted, so that the liveries of a rule are always in the same order (vmr_gui.py sorts the same way)
    for model in sorted(os.listdir(models_directory)):
        global model_list_len
        model_list_len = model_list_len + 1
        file_to_read = models_directory + "/" + model + "/aircraft.cfg"
        # strict=False: some MTL aircraft.cfg files contain a section or option twice (for example a second
        # [VERSION] section at the end of the file). The default strict parser would refuse the whole file.
        config = configparser.ConfigParser(strict=False)
        try:
            if verbose: print("Reading " + file_to_read + "...")
            fix_version_section(file_to_read)
            # MTL files are UTF-8 (sometimes with a BOM); a few older ones use a Windows code page instead.
            # Try UTF-8 first and fall back to cp1252, independent of the locale the script runs under.
            try:
                config.read(file_to_read, encoding="utf-8-sig")
            except UnicodeDecodeError:
                config = configparser.ConfigParser(strict=False)
                config.read(file_to_read, encoding="cp1252")
        except configparser.Error as err:
            print(err)
            errored_files.append(file_to_read)
            pass
        except UnicodeDecodeError as err:
            print("Could not decode " + file_to_read + ": " + str(err))
            errored_files.append(file_to_read)
            pass
        for section in config.sections():
            # [fltsim.0] in the MTL, [FLTSIM.0] in other libraries
            if "fltsim" in section.lower():
                global texture_len
                texture_len = texture_len + 1
                try:
                    acf_type = determine_aircraft_type(config, section)
                except Exception as err:
                    print(file_to_read + " [" + section + "] has no readable aircraft type (" + str(err) + "), skipping.")
                    errored_files.append(file_to_read)
                    continue

                # TypeCode cannot be blank.
                if acf_type == "":
                    print(file_to_read + " [" + section + "] has an empty aircraft type, skipping.")
                    errored_files.append(file_to_read)
                    continue

                try:
                    # title="A320AAF" or title=A320AAF: the ModelName is the title without the quotes
                    texture_title = config[section]["title"].strip().strip("\"").strip()
                    if texture_title == "":
                        raise ValueError("empty title")
                    callsign_prefix = determine_callsign_prefix(config[section])
                    texture_name = config[section].get("texture", "")
                    ui_variation = config[section].get("ui_variation", "")
                except Exception as err:
                    print(file_to_read + " [" + section + "] could not be read (" + str(err) + "), skipping.")
                    errored_files.append(file_to_read)
                    continue
                # Two liveries with the same title cannot be told apart by vPilot; the first one found is used.
                if texture_title in titles_seen:
                    print(file_to_read + " [" + section + "]: the title " + texture_title + " is already used by another livery, skipping.")
                    errored_files.append(file_to_read)
                    continue
                titles_seen.add(texture_title)
                if lib == "ivao":
                    standard = is_standard_livery(texture_name, ui_variation)
                    livery_info[texture_title] = (callsign_prefix, acf_type, texture_name.strip("\""), ui_variation.strip("\""), standard)
                    if not standard:
                        special_titles.add(texture_title)
                        if verbose: print("  Special livery: " + texture_title + " (" + ui_variation.strip("\"") + ")")
                    if callsign_prefix is None:
                        global no_code_len
                        no_code_len = no_code_len + 1
                        if verbose: print("  No airline code, left out: " + texture_title + " (" + ui_variation.strip("\"") + ")")
                        continue
                try:
                    model_list[callsign_prefix][acf_type].append(texture_title)
                except:
                    model_list[callsign_prefix][acf_type] = [texture_title]

    return model_list

# Goes through the models_list and writes the rules to the output file.
# Some airlines have multiple available textures for a single type. These are combined into one entry and the ModelNames are separated with "//"
# With standard_only, the special liveries are left out (see is_standard_livery).
def write_rules(model_list, output, standard_only):
    global airlines_len, special_skipped, special_kept, rules_len
    if not standard_only: airlines_len = airlines_len + len(model_list)

    for airline, type, variants, kept in group_rules(model_list, special_titles, standard_only):
        if standard_only:
            if kept:
                special_kept += len(variants)
            else:
                special_skipped += len(model_list[airline][type]) - len(variants)

        if(type.endswith("\"")):
            type = type[:-1]
        output.write(build_rule(airline, type, "//".join(variants)))
        if verbose and not standard_only: print("Created rule for airline " + airline + " type " + type)
        if not standard_only: rules_len = rules_len + 1

# Writes one VMR file.
def write_vmr(model_list, path, standard_only):
    output = open(path, "w", encoding="utf-8")
    output.write("<?xml version=\"1.0\" encoding=\"utf-8\"?> \n")
    output.write("<ModelMatchRuleSet> \n")
    write_rules(model_list, output, standard_only)
    output.write("</ModelMatchRuleSet> \n")
    output.write("<!-- VMR created by create-ivao-vmr https://github.com/andrewward2001/create-ivao-vmr -->")
    output.close()

def main():
    print("Building VMR for library: " + lib)
    print("Reading models from: " + os.path.abspath(models_directory))
    if not os.path.isdir(models_directory):
        print("ERROR: the directory " + models_directory + " does not exist.")
        print("Run this script from the root folder of the MTL library (the folder that contains \"SimObjects\"), or pass the path with -d.")
        return

    # Collect the rules first, so that a crash while reading the models never leaves a half-written VMR behind.
    model_list = create_model_list()

    output_directory.mkdir(parents=True, exist_ok=True)
    write_vmr(model_list, output_directory / output_file, False)
    if lib == "ivao":
        stem = Path(output_file).stem
        standard_file = stem + "_standard" + Path(output_file).suffix
        write_vmr(model_list, output_directory / standard_file, True)
    print("\n\nDone!")
    print("Processed: " + str(model_list_len) + " models.")
    print("Processed: " + str(texture_len) + " textures.")
    print("Processed: " + str(airlines_len) + " airlines.")
    print("Processed: " + str(rules_len) + " rules.")
    print("VMR created: " + os.path.abspath(output_directory / output_file))
    if lib == "ivao":
        print("Standard liveries only VMR created: " + os.path.abspath(output_directory / standard_file))
        print("  Special liveries left out: " + str(special_skipped) + ".")
        if special_kept > 0:
            print("  Special liveries kept because the airline has no standard livery for that aircraft type: " + str(special_kept) + ".")
        if no_code_len > 0:
            print("Liveries left out of both VMRs because they have no airline code a callsign can start with (ZZZ, military \"@\" codes) or because they are the invisible model: " + str(no_code_len) + ". Run the script with -v to see them.")
    if(len(fixed_files) != 0):
        print("\n\nSome aircraft.cfg files had a broken \"VERSION]\" section header. It was fixed to \"[VERSION]\" so the file could be read:")
        for file in fixed_files:
            print(file)
    if(len(errored_files) != 0):
        print("\n\nSome files had errors and were not included in the VMR:")
        for file in sorted(set(errored_files)):
            print(file)
        print("Usually this is because of an error where the file says [VERSION]. See GitHub for more details.")
        print("The VMR was still created but aircraft of this type will not show up unless the problem is fixed and the script is run again.")

if __name__ == "__main__":
    parse_command_line()
    try:
        main()
    except Exception:
        print("\n\nERROR: the script crashed. Details:")
        traceback.print_exc()
        print("The full output was saved to " + os.path.abspath(log_file) + ". Please attach it when reporting the problem on GitHub.")
    finally:
        if pause_at_end:
            try:
                input("\nPress Enter to close this window...")
            except EOFError:
                pass
