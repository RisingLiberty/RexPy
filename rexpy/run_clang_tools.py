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
import filelock
import psutil
import time

clang_tidy_first_pass_filename = ".clang-tidy_first_pass"
clang_tidy_second_pass_filename = ".clang-tidy_second_pass"
clang_tidy_format_filename = ".clang-format"
processes_in_flight_filename = "post_builds_in_flight.txt"
project = ""

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

def __is_post_build_in_flight(projects, ourProject):
  for project in projects:
    if ourProject in project:
      return True

  return False

def __wait_for_clang_tools_to_unlock():
  start_tries = 50
  tries = start_tries

  while tries > 0:
    lock = filelock.FileLock(f"{processes_in_flight_filename}.lock")

    # load all projects a post build command is currently in flight for
    # we need to keep the lock while scanning to avoid data races
    is_in_flight = False
    with open(processes_in_flight_filename, "r+") as f: 
      lines : list[str] = f.readlines()
      is_in_flight = __is_post_build_in_flight(lines, project)
          
    # if not, exit the loop, we can launch a new one
    if not is_in_flight:
      return


    print(f"[clang tools] waiting for clang tools to unlock for {project}")
    tries -= 1
    time.sleep(30)

  raise Exception(f"Failed to start run_clang_tools.py after {start_tries} tries")

def __lock_clang_tools(project):
  # create a file, if this file exists and contains the word "locked"
  # a post build in currently in flight, otherwise, we're free to go ahead
  __wait_for_clang_tools_to_unlock()

  print(f"[clang tools] locking clang tools for {project}")

  # The previous process has finished locking the file, we need to lock if for ourselves now
  lock = filelock.FileLock(f"{processes_in_flight_filename}.lock")
  with open(processes_in_flight_filename, "a") as f: 
    f.write(f"{project}\n")

def __unlock_clang_tools():
  lines = []

  print(f"[clang tools] unlocking clang tools for {project}")

  # read in all the lines first
  lock = filelock.FileLock(f"{processes_in_flight_filename}.lock")
  with open(processes_in_flight_filename, "r") as fp:
    lines = fp.readlines()

  # only write back the lines that don't include the project
  with open(processes_in_flight_filename, "w") as fp:
    for line in lines:
        if project not in line:
            fp.write(line)

  lock.release()

class Scopeguard:
  def __init__(self, callback):
    self.callback = callback

  def __del__(self):
    self.callback()

def run(projectName, compdb, srcRoot):
  script_path = os.path.dirname(__file__)
  global project
  project = projectName

  __copy_clang_config_files(compdb, srcRoot)

  clang_tidy_path = rexpy.required_tools.tool_paths_dict["clang_tidy_path"]
  clang_format_path = rexpy.required_tools.tool_paths_dict["clang_format_path"]
  clang_apply_replacements_path = rexpy.required_tools.tool_paths_dict["clang_apply_replacements_path"]
  clang_config_file = os.path.join(compdb, clang_tidy_first_pass_filename)

  # we use a file to lock other processes.
  # if multiple processes (like clang-tidy and clang-format)
  # are adjusting the code at the same time, we get invalid results
  # that's why we block post build so it only runs 1 at a time

  __lock_clang_tools(project)
  locker = Scopeguard(__unlock_clang_tools)

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