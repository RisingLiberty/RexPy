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
import rexpy.diagnostics
import rexpy.subproc
import rexpy.util
import rexpy.required_tools
import rexpy.rex_json
import shutil

clang_tidy_first_pass_filename = ".clang-tidy_first_pass"
clang_tidy_second_pass_filename = ".clang-tidy_second_pass"
clang_tidy_format_filename = ".clang-format"
root = rexpy.util.find_root()
settings = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
intermediate_folder = settings["intermediate_folder"]
build_folder = settings["build_folder"]
processes_in_flight_filename = os.path.join(root, intermediate_folder, build_folder, "ninja", "post_builds_in_flight.tmp")
project = ""

def __run_command(command):
  proc = rexpy.subproc.run(command)
  streamdata = proc.communicate()[0]
  return proc.returncode

def run(projectName, compdb, srcRoot):
  script_path = os.path.dirname(__file__)
  global project
  project = projectName

  headerFilters = rexpy.util.retrieve_header_filters(compdb, project)
  headerFiltersRegex = rexpy.util.create_header_filter_regex(headerFilters)

  clang_tidy_path = rexpy.required_tools.tool_paths_dict["clang_tidy_path"]
  clang_format_path = rexpy.required_tools.tool_paths_dict["clang_format_path"]
  clang_apply_replacements_path = rexpy.required_tools.tool_paths_dict["clang_apply_replacements_path"]
  clang_config_file = os.path.join(compdb, clang_tidy_first_pass_filename)

  rexpy.diagnostics.log_info("Running clang-tidy - auto fixes")
  rc = __run_command(f"py {script_path}/run_clang_tidy.py -clang-tidy-binary={clang_tidy_path} -clang-apply-replacements-binary={clang_apply_replacements_path} -config-file={clang_config_file} -p={compdb} -header-filter={headerFiltersRegex} -quiet -fix") # force clang compiler, as clang-tools expect it

  if rc != 0:
    raise Exception("clang-tidy auto fixes failed")

  rexpy.diagnostics.log_info("Running clang-format")
  rc = __run_command(f"py {script_path}/run_clang_format.py --clang-format-executable={clang_format_path} -r -i {srcRoot}")

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
  rexpy.diagnostics.log_info(f"Executing {__file__}")

 # execute the script
  run(args.project, args.compdb, args.srcroot)

 # print. We're done.
  rexpy.diagnostics.log_info("Done.")

  exit(0)