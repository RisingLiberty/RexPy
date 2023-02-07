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
import subprocess
import rexpy.diagnostics
import rexpy.util
import rexpy.required_tools
import rexpy.diagnostics
import shutil

clang_tidy_first_pass_filename = ".clang-tidy_first_pass"
clang_tidy_second_pass_filename = ".clang-tidy_second_pass"
clang_tidy_format_filename = ".clang-format"

def __run_command(command):
  proc = subprocess.Popen(command)
  streamdata = proc.communicate()[0]
  return proc.returncode

def __copy_clang_config_files(targetDir, srcRoot):
  clang_tidy_firstpass_config_src_path = os.path.join(rexpy.util.find_in_parent(srcRoot, clang_tidy_first_pass_filename), clang_tidy_first_pass_filename)
  clang_tidy_secondpass_config_src_path = os.path.join(rexpy.util.find_in_parent(srcRoot, clang_tidy_first_pass_filename), clang_tidy_second_pass_filename)
  clang_format_config_src_path = os.path.join(rexpy.util.find_in_parent(srcRoot, clang_tidy_first_pass_filename), clang_tidy_format_filename)

  clang_tidy_firstpass_config_dst_path = os.path.join(targetDir, clang_tidy_first_pass_filename)
  clang_tidy_secondpass_config_dst_path = os.path.join(targetDir, clang_tidy_second_pass_filename)
  clang_format_config_dst_path = os.path.join(targetDir, clang_tidy_format_filename)
  
  shutil.copy(clang_tidy_firstpass_config_src_path, clang_tidy_firstpass_config_dst_path)
  shutil.copy(clang_tidy_secondpass_config_src_path, clang_tidy_secondpass_config_dst_path)
  shutil.copy(clang_format_config_src_path, clang_format_config_dst_path)

def run(projectName, compdb, srcRoot):
  script_path = os.path.dirname(__file__)

  __copy_clang_config_files(compdb, srcRoot)

  clang_tidy_path = rexpy.required_tools.tool_paths_dict["clang_tidy_path"]
  clang_format_path = rexpy.required_tools.tool_paths_dict["clang_format_path"]
  clang_apply_replacements_path = rexpy.required_tools.tool_paths_dict["clang_apply_replacements_path"]
  clang_config_file = os.path.join(compdb, clang_tidy_first_pass_filename)

  rexpy.diagnostics.log_info("Running clang-tidy - auto fixes")
  rc = __run_command(f"py {script_path}/run_clang_tidy.py -clang-tidy-binary={clang_tidy_path} -clang-apply-replacements-binary={clang_apply_replacements_path} -config-file={clang_config_file} -p={compdb} -header-filter=.* -quiet -fix") # force clang compiler, as clang-tools expect it

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