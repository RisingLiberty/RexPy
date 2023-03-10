# ============================================ 
#
# Author: Nick De Breuck
# Twitter: @nick_debreuck
# 
# File: test.py
# Copyright (c) Nick De Breuck 2023
#
# ============================================

import os
import threading
import time
import signal
import regis.required_tools
import regis.util
import regis.task_raii_printing
import regis.rex_json
import regis.code_coverage
import regis.diagnostics
import regis.generation
import regis.build

from pathlib import Path
from datetime import datetime

root_path = regis.util.find_root()
tool_paths_dict = regis.required_tools.tool_paths_dict
settings = regis.rex_json.load_file(os.path.join(root_path, "build", "config", "settings.json"))
__pass_results = {}

def get_pass_results():
  return __pass_results

def __is_in_line(line : str, keywords : list[str]):
  for keyword in keywords:
    if keyword.lower() in line.lower():
      return True

  return False

def __default_output_callback(output):
  error_keywords = ["failed", "error"]
  warn_keywords = ["warning"]

  for line in iter(output.readline, b''):
    new_line : str = line.decode('UTF-8')
    if new_line.endswith('\n'):
      new_line = new_line.removesuffix('\n')

    if __is_in_line(new_line, error_keywords):
      regis.diagnostics.log_err(new_line)
      continue
    elif __is_in_line(new_line, warn_keywords):
      regis.diagnostics.log_warn(new_line)
      continue
    
    regis.diagnostics.log_no_color(new_line)

def __run_include_what_you_use(fixIncludes = False):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running include-what-you-use")

  regis.generation.new_generation(os.path.join(root_path, "build", "config", "settings.json"), "")

  intermediate_folder = os.path.join(root_path, settings["intermediate_folder"], settings["build_folder"])
  result = regis.util.find_all_files_in_folder(intermediate_folder, "compile_commands.json")
    
  for compiler_db in result:
    iwyu_path = tool_paths_dict["include_what_you_use_path"]
    iwyu_tool_path = os.path.join(Path(iwyu_path).parent, "iwyu_tool.py")
    fix_includes_path = os.path.join(Path(iwyu_path).parent, "fix_includes.py")
    compiler_db_folder = Path(compiler_db).parent
    output_path = os.path.join(compiler_db_folder, "iwyu_output.log")
    os.system(f"py {iwyu_tool_path} -v -p={compiler_db_folder} > {output_path}") # needs to use os.system or iwyu will parse the command incorrectly
    if fixIncludes:
      os.system(f"py {fix_includes_path} --update_comments --safe_headers < {output_path}")
    
    regis.diagnostics.log_info(f"include what you use info saved to {output_path}")

  return 0

# the compdbPath directory contains all the files needed to configure clang tools
# this includes the compiler databse, clang tidy config files, clang format config files
# and a custom generated project file (in run_clang_tools.py), which should have the same filename as the source root directory
# of the project you're testing
def __get_project_name(compdbPath):
  dirs = os.listdir(compdbPath)
  for dir in dirs:
    if ".project" in dir:
      return dir.split(".")[0]
  
  return ""

def __run_clang_tidy():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running clang-tidy")

  regis.generation.new_generation(os.path.join(root_path, "build", "config", "settings.json"), "")

  intermediate_folder = os.path.join(root_path, settings["intermediate_folder"], settings["build_folder"])
  result = regis.util.find_all_files_in_folder(intermediate_folder, "compile_commands.json")

  rc = 0
  for compiler_db in result:
    script_path = os.path.dirname(__file__)
    clang_tidy_path = tool_paths_dict["clang_tidy_path"]
    clang_apply_replacements_path = tool_paths_dict["clang_apply_replacements_path"]
    compiler_db_folder = Path(compiler_db).parent
    config_file_path = f"{compiler_db_folder}/.clang-tidy_second_pass"

    project_name = __get_project_name(compiler_db_folder)
    header_filters = regis.util.retrieve_header_filters(compiler_db_folder, project_name)
    header_filters_regex = regis.util.create_header_filter_regex(header_filters)

    cmd = f"py \"{script_path}/run_clang_tidy.py\""
    cmd += f" -clang-tidy-binary=\"{clang_tidy_path}\""
    cmd += f" -clang-apply-replacements-binary=\"{clang_apply_replacements_path}\""
    cmd += f" -config-file=\"{config_file_path}\""
    cmd += f" -p=\"{compiler_db_folder}\""
    cmd += f" -header-filter={header_filters_regex}" # only care about headers of the current project
    cmd += f" -quiet"

    regis.diagnostics.log_info(f"executing: {cmd}")

    proc = regis.util.run_subprocess_with_callback(cmd, __default_output_callback)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"clang-tidy failed for {compiler_db}")
      regis.diagnostics.log_err(f"config file: {config_file_path}")
    rc |= new_rc

  return rc

def __generate_test_files(sharpmakeArgs):
  root = regis.util.find_root()
  settings_path = os.path.join(root, "build", "config", "settings.json")
  proc = regis.generation.new_generation(settings_path, sharpmakeArgs)
  proc.wait()
  return proc.returncode

def __find_projects_with_suffix(directory, suffix):
  projects = []
  for root, dirs, files in os.walk(directory):
    for file in files:
      filename = Path(file).name
      if filename.lower().endswith(f"{suffix}.nproj".lower()):
        projects.append(Path(filename).stem)

  return projects

def __build_test_files(projectSuffix : str, configs : [str], compilers : [str]):
  should_clean = False

  result = 0

  intermediate_folder = settings["intermediate_folder"]
  build_folder = settings["build_folder"]

  directory = os.path.join(root_path, intermediate_folder, build_folder, "ninja")
  projects = __find_projects_with_suffix(directory, projectSuffix)

  for project in projects:
    for config in configs:
      for compiler in compilers:
        result |= regis.build.new_build(project, config, compiler, should_clean)

  return result

def __build_non_test_files(configs : [str], compilers : [str]):
  should_clean = False

  result = 0

  intermediate_folder = settings["intermediate_folder"]
  build_folder = settings["build_folder"]

  directory = os.path.join(root_path, intermediate_folder, build_folder, "ninja")
  projects = __find_projects_with_suffix(directory, "")

  for project in projects:
    # skip all test projects
    if "test" in project or "_asan" in project or "_ubsan" in project or "_fuzzy" in project:
      continue

    for config in configs:
      for compiler in compilers:
        result |= regis.build.new_build(project, config, compiler, should_clean)

  return result

def __find_test_programs(folder, regex):
  intermediate_folder = os.path.join(folder)
  regis.diagnostics.log_info(f"looking for executables in {os.path.join(root_path, intermediate_folder)}")
  result = regis.util.find_all_files_in_folder(os.path.join(root_path, intermediate_folder), regex)
  coverage_programs : list[str] = []
  for res in result:
    if regis.util.is_executable(res):
      coverage_programs.append(res.absolute().__str__())

  return coverage_programs

# unit tests
def __generate_tests():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating unit test projects")
  return __generate_test_files("/generateUnitTests")

def __build_tests():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building tests")
  return __build_test_files("test", ["debug", "debug_opt", "release"], ["msvc", "clang"])

def __run_unit_tests():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running unit tests")
  unit_test_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*test*")
  
  rc = 0
  for program in unit_test_programs:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    proc = regis.util.run_subprocess(program)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"unit test failed for {program}") # use full path to avoid ambiguity
    rc |= new_rc

  return rc

# coverage
def __generate_coverage():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating coverage code")
  return __generate_test_files("/generateUnitTests /enableCoverage")

def __build_coverage():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building coverage code")
  return __build_test_files("_coverage", ["coverage"], ["clang"])

def __run_coverage():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running coverage")
  unit_test_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*coverage*")

  rc = 0
  for program in unit_test_programs:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    os.environ["LLVM_PROFILE_FILE"] = __get_coverage_rawdata_filename(program) # this is what llvm uses to set the raw data filename for the coverage data
    proc = regis.util.run_subprocess(program)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"unit test failed for {program}") # use full path to avoid ambiguity
    rc |= new_rc

  return unit_test_programs

def __relocate_coverage_data(programsRun : list[str]):
  task_print = regis.task_raii_printing.TaskRaiiPrint("relocating coverage files")
  data_files = []

  for program in programsRun:
    coverage_rawdata_filename = __get_coverage_rawdata_filename(program)
    newPath = os.path.join(Path(program).parent, coverage_rawdata_filename)
    if (os.path.exists(newPath)):
      os.remove(newPath)
    os.rename(coverage_rawdata_filename, newPath)
    data_files.append(newPath)
    
  return data_files

def __index_rawdata_files(rawdataFiles : list[str]):
  task_print = regis.task_raii_printing.TaskRaiiPrint("indexing rawdata files")
  output_files = []

  for file in rawdataFiles:
    output_files.append(regis.code_coverage.create_index_rawdata(file))

  return output_files

def __create_coverage_reports(programsRun, indexdataFiles):
  task_print = regis.task_raii_printing.TaskRaiiPrint("creating coverage reports")

  rc = 0
  for index in range(len(programsRun)):
    program = programsRun[index]
    indexdata_file = indexdataFiles[index]

    if Path(program).stem != Path(indexdata_file).stem:
      rc = 1
      regis.diagnostics.log_err(f"program stem doesn't match coverage file stem: {Path(program).stem} != {Path(indexdata_file).stem}")

    regis.code_coverage.create_line_oriented_report(program, indexdata_file)
    regis.code_coverage.create_file_level_summary(program, indexdata_file)
    regis.code_coverage.create_lcov_report(program, indexdata_file)

  return rc

def __parse_coverage_reports(indexdataFiles):
  task_print = regis.task_raii_printing.TaskRaiiPrint("parsing coverage reports")

  rc = 0
  for indexdata_file in indexdataFiles:
    report_filename = regis.code_coverage.get_file_level_summary_filename(indexdata_file)
    rc |= regis.code_coverage.parse_file_summary(report_filename)

  return rc

def __get_coverage_rawdata_filename(program : str):
  return f"{Path(program).stem}.profraw"

# asan
def __generate_address_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating address sanitizer code")
  return __generate_test_files("/generateUnitTests /enableAddressSanitizer")

def __build_address_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building address sanitizer code")
  return __build_test_files("_asan", ["address_sanitizer"], ["clang"])

def __run_address_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running address sanitizer tests")
  unit_test_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*asan*")
  
  rc = 0
  for program in unit_test_programs:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    log_folder_path = Path(program).parent
    log_folder = log_folder_path.as_posix()
    
    # for some reason, setting an absolute path for the log folder doesn't work
    # so we have to set the working directory of the program to where it's located so the log file will be there as well
    # ASAN_OPTIONS common flags: https://github.com/google/sanitizers/wiki/SanitizerCommonFlags
    # ASAN_OPTIONS flags: https://github.com/google/sanitizers/wiki/AddressSanitizerFlags
    asan_options = f"print_stacktrace=1:log_path=asan.log"
    os.environ["ASAN_OPTIONS"] = asan_options # print callstacks and save to log file
    
    proc = regis.util.run_subprocess_with_working_dir(program, log_folder)
    new_rc = regis.util.wait_for_process(proc)
    log_file_path = os.path.join(log_folder, f"asan.log.{proc.pid}")
    if new_rc != 0 or os.path.exists(log_file_path):
      regis.diagnostics.log_err(f"address sanitizer failed for {program}") # use full path to avoid ambiguity
      regis.diagnostics.log_err(f"for more info, please check: {log_file_path}")
      new_rc = 1
    rc |= new_rc

  return rc

# ubsan
def __generate_undefined_behavior_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating undefined behavior sanitizer code")
  return __generate_test_files("/generateUnitTests /enableUBSanitizer")

def __build_undefined_behavior_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building undefined behavior sanitizer code")
  return __build_test_files("_ubsan", ["undefined_behavior_sanitizer"], ["clang"])

def __run_undefined_behavior_sanitizer():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running undefined behavior sanitizer tests")
  unit_test_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*ubsan*")
  
  rc = 0
  for program in unit_test_programs:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    log_folder_path = Path(program).parent
    log_folder = log_folder_path.as_posix()
    
    # for some reason, setting an absolute path for the log folder doesn't work
    # so we have to set the working directory of the program to where it's located so the log file will be there as well
    # UBSAN_OPTIONS common flags: https://github.com/google/sanitizers/wiki/SanitizerCommonFlags
    ubsan_options = f"print_stacktrace=1:log_path=ubsan.log"
    os.environ["UBSAN_OPTIONS"] = ubsan_options # print callstacks and save to log file
    proc = regis.util.run_subprocess_with_working_dir(program, log_folder)
    new_rc = regis.util.wait_for_process(proc)
    log_file_path = os.path.join(log_folder, f"ubsan.log.{proc.pid}")
    if new_rc != 0 or os.path.exists(log_file_path): # if there's a ubsan.log.pid created, the tool found issues
      regis.diagnostics.log_err(f"undefined behavior sanitizer failed for {program}") # use full path to avoid ambiguity
      regis.diagnostics.log_err(f"for more info, please check: {log_file_path}")
      new_rc = 1
    rc |= new_rc

  return rc

# fuzzy
def __generate_fuzzy_testing():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating fuzzy testing code")
  return __generate_test_files("/enableFuzzyTesting")

def __build_fuzzy_testing():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building fuzzy testing code")
  return __build_test_files("_fuzzy", ["fuzzy"], ["clang"])

def __run_fuzzy_testing():
  task_print = regis.task_raii_printing.TaskRaiiPrint("running fuzzy tests")
  fuzzy_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*fuzzy*")
  
  rc = 0
  for program in fuzzy_programs:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    log_folder_path = Path(program).parent
    log_folder = log_folder_path.as_posix()
    
    # for some reason, setting an absolute path for the log folder doesn't work
    # so we have to set the working directory of the program to where it's located so the log file will be there as well
    # Can't use both ASAN as well as UBSAN options, so we'll set the same for both and hope that works
    # https://gcc.gnu.org/bugzilla/show_bug.cgi?id=94328
    # https://stackoverflow.com/questions/60774638/logging-control-for-address-sanitizer-plus-undefined-behavior-sanitizer
    asan_options = f"print_stacktrace=1:log_path=fuzzy.log"
    ubsan_options = f"print_stacktrace=1:log_path=fuzzy.log"
    os.environ["ASAN_OPTIONS"] = asan_options # print callstacks and save to log file
    os.environ["UBSAN_OPTIONS"] = ubsan_options # print callstacks and save to log file
    num_runs = 10000 # we'll run 10'000 fuzzy tests, should be more than enough
    proc = regis.util.run_subprocess_with_working_dir(f"{program} -runs={num_runs}", log_folder)
    new_rc = regis.util.wait_for_process(proc)
    log_file_path = os.path.join(log_folder, f"fuzzy.log.{proc.pid}")
    if new_rc != 0 or os.path.exists(log_file_path): # if there's a ubsan.log.pid created, the tool found issues
      regis.diagnostics.log_err(f"fuzzy testing failed for {program}") # use full path to avoid ambiguity
      if os.path.exists(log_file_path):
        regis.diagnostics.log_err(f"issues found while fuzzing!")
        regis.diagnostics.log_err(f"for more info, please check: {log_file_path}")
      new_rc = 1
    rc |= new_rc

  return rc

# auto tests
def __generate_auto_tests():
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating auto tests")
  return __generate_test_files("/noClangTools")

def __build_auto_tests():
  task_print = regis.task_raii_printing.TaskRaiiPrint("building auto tests")
  return __build_non_test_files(["debug", "debug_opt", "release"], ["msvc", "clang"])

def __run_auto_tests(timeoutInSeconds):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running auto tests")
  unit_test_programs = __find_test_programs(os.path.join(settings["intermediate_folder"], settings["build_folder"], "ninja"), "*")
  
  rc = 0
  for program in unit_test_programs:
    if "test" in program or "_asan" in program or "_ubsan" in program or "_fuzzy" in program:
      continue

    regis.diagnostics.log_info(f"running: {Path(program).name}")
    proc = regis.util.run_subprocess(program)

    # wait for program to finish on a different thread so we can terminate it on timeout
    thread = threading.Thread(target=lambda: proc.wait())
    thread.start()

    # wait for timeout to trigger or until the program exits
    now = time.time()
    duration = 0
    killed_process = False
    max_seconds = timeoutInSeconds
    while True:
      duration = time.time() - now
      if not thread.is_alive():
        break
      
      if duration > max_seconds:
        proc.terminate() 
        killed_process = True
        break

    # makes sure that we get an error code even if the program crashed
    proc.communicate()
    new_rc = proc.returncode
    
    if new_rc != 0:
      if killed_process:
        regis.diagnostics.log_warn(f"auto test timeout triggered for {program} after {max_seconds} seconds") # use full path to avoid ambiguity
      else:
        rc |= new_rc
        regis.diagnostics.log_err(f"auto test failed for {program} with returncode {new_rc}") # use full path to avoid ambiguity

  return rc

# public API
def test_include_what_you_use():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __run_include_what_you_use()

  if rc != 0:
    regis.diagnostics.log_err(f"include-what-you-use pass failed")

  __pass_results["include-what-you-use"] = rc

def test_clang_tidy():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __run_clang_tidy() # works
  if rc != 0:
    regis.diagnostics.log_err(f"clang-tidy pass failed")

  __pass_results["clang-tidy"] = rc

def test_unit_tests():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_tests() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate tests")
  __pass_results["unit tests generation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __build_tests() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build tests")
  __pass_results["unit tests building"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __run_unit_tests() # works
  if rc != 0:
    regis.diagnostics.log_err(f"unit tests failed")
  __pass_results["unit tests result"] = rc

def test_code_coverage():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_coverage() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate coverage")
  __pass_results["coverage generation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __build_coverage() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build coverage")
  __pass_results["coverage building"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  programs_run = __run_coverage() # works
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rawdata_files = __relocate_coverage_data(programs_run) # works
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  indexdata_files = __index_rawdata_files(rawdata_files) # works
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __create_coverage_reports(programs_run, indexdata_files) # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to create coverage reports")
  __pass_results["coverage report creation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __parse_coverage_reports(indexdata_files) # works
  if rc != 0:
    regis.diagnostics.log_err(f"Not all the code was covered")
  __pass_results["coverage report result"] = rc

def test_asan():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_address_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate asan code")
  __pass_results["address sanitizer generation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __build_address_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build asan code")
  __pass_results["address sanitizer building"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __run_address_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with asan")
  __pass_results["address sanitizer result"] = rc

def test_ubsan():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_undefined_behavior_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate ubsan code")
  __pass_results["undefined behavior sanitizer generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __build_undefined_behavior_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build ubsan code")
  __pass_results["undefined behavior sanitizer building"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __run_undefined_behavior_sanitizer() # works
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with ubsan")
  __pass_results["undefined behavior sanitizer result"] = rc

def test_fuzzy_testing():
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_fuzzy_testing() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate fuzzy code")
  __pass_results["fuzzy testing generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __build_fuzzy_testing() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build fuzzy code")
  __pass_results["fuzzy testing building"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __run_fuzzy_testing() # works
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with fuzzy")
  __pass_results["fuzzy testing result"] = rc

def run_auto_tests(timeoutInSeconds : int):
  rc = 0

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = __generate_auto_tests() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate auto test code")
  __pass_results["auto testing generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __build_auto_tests() # works
  if rc != 0:
    regis.diagnostics.log_err(f"failed to build auto test code")
  __pass_results["auto testing building"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= __run_auto_tests(timeoutInSeconds) # works
  if rc != 0:
    regis.diagnostics.log_err(f"auto tests failed")
  __pass_results["auto testing result"] = rc
