# ============================================ 
#
# Author: Nick De Breuck
# Twitter: @nick_debreuck
# 
# File: run_clang_tools.py
# Copyright (c) Nick De Breuck 2023
#
# ============================================

import os
import argparse
import regis.diagnostics
import regis.subproc
import regis.util
import regis.required_tools
import regis.rex_json
import shutil

clang_tidy_first_pass_filename = ".clang-tidy_first_pass"
clang_tidy_second_pass_filename = ".clang-tidy_second_pass"
clang_tidy_format_filename = ".clang-format"
root = regis.util.find_root()
settings = regis.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
intermediate_folder = settings["intermediate_folder"]
build_folder = settings["build_folder"]
processes_in_flight_filename = os.path.join(root, intermediate_folder, build_folder, "ninja", "post_builds_in_flight.tmp")
project = ""

def __quoted_path(path):
  quote = "\""
  return f"{quote}{path}{quote}"

def __run_command(command):
  proc = regis.subproc.run(command)
  streamdata = proc.communicate()[0]
  return proc.returncode

def run(projectName, compdb, srcRoot, allChecks, regex):
  script_path = os.path.dirname(__file__)
  global project
  project = projectName

  headerFilters = regis.util.retrieve_header_filters(compdb, project)
  headerFiltersRegex = regis.util.create_header_filter_regex(headerFilters)

  clang_tidy_path = regis.required_tools.tool_paths_dict["clang_tidy_path"]
  clang_format_path = regis.required_tools.tool_paths_dict["clang_format_path"]
  clang_apply_replacements_path = regis.required_tools.tool_paths_dict["clang_apply_replacements_path"]
  clang_config_file = os.path.join(compdb, clang_tidy_first_pass_filename)

  compdb_path = os.path.join(compdb, "compile_commands.json")
  if os.path.exists(compdb_path):
    regis.diagnostics.log_info(f"Compiler db found at {compdb_path}")

    regis.diagnostics.log_info("Running clang-tidy - auto fixes")
    cmd = f"py {__quoted_path(script_path)}/run_clang_tidy.py -clang-tidy-binary={__quoted_path(clang_tidy_path)} -clang-apply-replacements-binary={__quoted_path(clang_apply_replacements_path)} -config-file={__quoted_path(clang_config_file)} -p={__quoted_path(compdb)} -header-filter={headerFiltersRegex} -quiet -fix {regex}"
    rc = __run_command(cmd) # force clang compiler, as clang-tools expect it

    if rc != 0:
      raise Exception("clang-tidy auto fixes failed")
  
    if allChecks:
      clang_config_file = os.path.join(compdb, clang_tidy_second_pass_filename)
      regis.diagnostics.log_info("Running clang-tidy - all checks")  
      cmd = f"py {__quoted_path(script_path)}/run_clang_tidy.py -clang-tidy-binary={__quoted_path(clang_tidy_path)} -clang-apply-replacements-binary={__quoted_path(clang_apply_replacements_path)} -config-file={__quoted_path(clang_config_file)} -p={__quoted_path(compdb)} -header-filter={headerFiltersRegex} -quiet {regex}"
      rc = __run_command(cmd) # force clang compiler, as clang-tools expect it


  else:
    regis.diagnostics.log_warn(f"No compiler db found at {compdb}")

  regis.diagnostics.log_info("Running clang-format")
  rc = __run_command(f"py {__quoted_path(script_path)}/run_clang_format.py --clang-format-executable={__quoted_path(clang_format_path)} -r -i {srcRoot}")

  if rc != 0:
    raise Exception("clang-format failed")

if __name__ == "__main__":
  # arguments setups
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)

  parser.add_argument("-p", "--project", help="project name")
  parser.add_argument("-compdb", help="compiler database folder")
  parser.add_argument("-srcroot", help="src root folder")
  
  args, unknown = parser.parse_known_args()

 # useful for debugging
  regis.diagnostics.log_info(f"Executing {__file__}")

 # execute the script
  run(args.project, args.compdb, args.srcroot)

 # print. We're done.
  regis.diagnostics.log_info("Done.")

  exit(0)