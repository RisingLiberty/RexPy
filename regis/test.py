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
import threading
import subprocess
import re
import regis.required_tools
import regis.util
import regis.task_raii_printing
import regis.rex_json
import regis.code_coverage
import regis.diagnostics
import regis.generation
import regis.build
import regis.dir_watcher

from pathlib import Path
from datetime import datetime

root_path = regis.util.find_root()
tool_paths_dict = regis.required_tools.tool_paths_dict
settings = regis.rex_json.load_file(os.path.join(root_path, regis.util.settingsPathFromRoot))
_pass_results = {}

iwyu_intermediate_dir = "iwyu"
clang_tidy_intermediate_dir = "clang_tidy"
unit_tests_intermediate_dir = "unit_tests"
coverage_intermediate_dir = "coverage"
asan_intermediate_dir = "asan"
ubsan_intermediate_dir = "ubsan"
fuzzy_intermediate_dir = "fuzzy"
auto_test_intermediate_dir = "auto_test"

def get_pass_results():
  return _pass_results

def _is_in_line(line : str, keywords : list[str]):
  regex = "((error).(cpp))|((error).(h))"

  for keyword in keywords:
    if keyword.lower() in line.lower():
      return not re.search(regex, line.lower()) # make sure that lines like 'error.cpp' don't return positive

  return False

def _symbolic_print(line, filterLines : bool = False):
  error_keywords = ["failed", "error"]
  warn_keywords = ["warning"]

  if _is_in_line(line, error_keywords):
    regis.diagnostics.log_err(line)
  elif _is_in_line(line, warn_keywords):
    regis.diagnostics.log_warn(line)
  elif not filterLines:
    regis.diagnostics.log_no_color(line)

def _default_output_callback(pid, output, isStdErr, filterLines):
  logs_dir = os.path.join(settings["intermediate_folder"], "logs")
  filename = f"output_{pid}.log"
  if isStdErr:
    filename = f"errors_{pid}.log"

  filepath = os.path.join(logs_dir, filename)
  if os.path.exists(filepath):
    os.remove(filepath)
  elif not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

  with open(filepath, "a+") as f:

    for line in iter(output.readline, b''):
      new_line : str = line.decode('UTF-8')
      if new_line.endswith('\n'):
        new_line = new_line.removesuffix('\n')

      _symbolic_print(new_line, filterLines)      
      f.write(f"{new_line}\n")

    regis.diagnostics.log_info(f"full output saved to {filepath}")

def _run_include_what_you_use(fixIncludes = False, shouldClean : bool = True, singleThreaded : bool = False):
  """Run include what you use on the codebase"""
  def _run(iwyuPath, compdb, outputPath, impPath, lock):
      """Run the actual include-what-you-use command and save the output into a log file"""
      # create the command line to launch include-what-you-use
      cmd = ""
      cmd += f"py {iwyuPath} -v -p={compdb}"
      cmd += f" -- -Xiwyu --quoted_includes_first"
      
      if impPath != "" and os.path.exists(impPath):
        cmd += f" -Xiwyu --mapping_file={impPath}"

      # run include-what-you-use and save the output into a file
      output = subprocess.getoutput(cmd)
      with open(outputPath, "w") as f:
        f.write(output)
      output_lines = output.split('\n')

      # print the output using our color coding
      # to detect if it's an error, warning or regular log
      with lock:
        for line in output_lines:
          _symbolic_print(line)

        # log to the user that output has been saved
        regis.diagnostics.log_info(f"include what you use info saved to {outputPath}")
    
  task_print = regis.task_raii_printing.TaskRaiiPrint("running include-what-you-use")

  # to avoid clashing with other builds, we create our own intermediate folder
  intermediate_folder = os.path.join(root_path, settings["intermediate_folder"], settings["build_folder"], iwyu_intermediate_dir)

  # because we have the intermediates of iwyu in its own intermediate folder
  # we can safely clean it without affecting other builds
  if shouldClean:
    regis.diagnostics.log_info(f"cleaning {intermediate_folder}..")
    regis.util.remove_folders_recursive(intermediate_folder)

  # perform a new generation to make sure we actually have files to go over
  generated_files = _generate_test_files(regis.generation.create_config(f'-intermediate-dir={iwyu_intermediate_dir} -disable-clang-tidy-for-thirdparty -IDE None'))

  # get the compiler dbs that are just generated
  result = list(filter(lambda file: 'compile_commands.json' in file, generated_files))

  # find all the compiler dbs.
  # these act as input for include-what-you-use
  result = regis.util.find_all_files_in_folder(intermediate_folder, "compile_commands.json")
    
  threads : list[threading.Thread] = []
  output_files_per_project : dict[str, list] = {}
  lock = threading.Lock()

  iwyu_path = tool_paths_dict["include_what_you_use_path"]
  iwyu_tool_path = os.path.join(Path(iwyu_path).parent, "iwyu_tool.py")

  # create the include-what-you-use jobs
  for compiler_db in result:
    compiler_db_folder = Path(compiler_db).parent
    impPath = os.path.join(compiler_db_folder, "iwyu.imp")
    output_path = os.path.join(compiler_db_folder, "iwyu_output.log")
    project_name = _get_project_name_of_compdb(compiler_db_folder)

    # if we haven't compiled this project yet, prep the dict for it
    if project_name not in output_files_per_project:
      output_files_per_project[project_name] = []

    output_files_per_project[project_name].append(output_path)

    thread = threading.Thread(target=_run, args=(iwyu_tool_path, compiler_db, output_path, impPath, lock))
    thread.start()

    # very simple way of splitting single threaded with multi threaded mode
    # if we're single thread, we create a thread and immediately join it
    # if we're using multi threaded mode, we join them after all of them have been created
    if singleThreaded:
      thread.join() 
    else:
      threads.append(thread)

  # join all the threads after they've all been created
  # this is basically a no op if we're running in single threaded mode
  for thread in threads:
    thread.join()

  threads.clear()

  # because different configs could require different symbols or includes
  # we need to process all configs first, then process each output file for each config
  # for a given project and only if an include is not needed in all configs
  # take action and remove it or replace it with a forward declare
  # this can't be multithreaded
  if fixIncludes:
    regis.diagnostics.log_info(f'Applying fixes..')

  fix_includes_path = os.path.join(Path(iwyu_path).parent, "fix_includes.py")

  # this is the actual run in trying to fix the includes
  # however it can be faked when fixIncludes is false
  # if so, it'll do a dry run without changing anything
  # it'll still return a proper return code
  # indicating if anything needs to be changed
  rc = 0
  for key in output_files_per_project.keys():
    output_files = output_files_per_project[key]
    lines = []
    regis.diagnostics.log_info(f'processing: {key}')

    # include-what-you-use uses the output path of iwyu to determine what needs to be fixed
    # we merge all the outputs of all runs of iwyu on a project in different configs
    # and pass that temporary file over to include what you use
    for file in output_files:
      f = open(file, "r")
      lines.extend(f.readlines())

    filename = f'{key}_tmp.iwyu'
    filepath = os.path.join(intermediate_folder, filename)
    f = open(filepath, "w")
    f.writelines(lines)
    f.close()

    # create the fix includes command line
    cmd = f"py {fix_includes_path} --noreorder --process_merged=\"{filepath}\" --nocomments --nosafe_headers"

    if fixIncludes == False:
      cmd += f" --dry_run"

    # run the fix includes command line
    rc |= os.system(f"{cmd}")  

  return rc

# the compdbPath directory contains all the files needed to configure clang tools
# this includes the compiler database, clang tidy config files, clang format config files
# and a custom generated project file, which should have the same filename as the source root directory
# of the project you're testing
def _get_project_name_of_compdb(compdbPath):
  dirs = os.listdir(compdbPath)
  for dir in dirs:
    if ".project" in dir:
      return dir.split(".")[0]
  
  return ""

def _run_clang_tidy(filesRegex, shouldClean : bool = True, singleThreaded : bool = False, filterLines : bool = False, shouldFix : bool = False):
  """Run clang-tidy on the codebase"""
  rc = [0]
  def _run(cmd : str, rc : int):
    """Run the actual clang-tidy command"""
    regis.diagnostics.log_info(f"executing: {cmd}")
    proc = regis.util.run_subprocess_with_callback(cmd, _default_output_callback, filterLines)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"clang-tidy failed for {compiler_db}")
      regis.diagnostics.log_err(f"config file: {config_file_path}")
    rc[0] |= new_rc

  task_print = regis.task_raii_printing.TaskRaiiPrint("running clang-tidy")

  # to avoid clashing with other builds, we generate our projects and intermediate in our own folder
  intermediate_folder = os.path.join(root_path, settings["intermediate_folder"], settings["build_folder"], clang_tidy_intermediate_dir)

  # because our project and intermediates are generated into our own folder, this makes it safe to clean it
  if shouldClean:
    regis.diagnostics.log_info(f"cleaning {intermediate_folder}..")
    regis.util.remove_folders_recursive(intermediate_folder)

  # perform a new generation to make sure we actually have files to go over
  generated_files = _generate_test_files(regis.generation.create_config(f'-intermediate-dir={clang_tidy_intermediate_dir} -disable-clang-tidy-for-thirdparty -IDE None'))

  # get the compiler dbs that are just generated
  result = list(filter(lambda file: 'compile_commands.json' in file, generated_files))

  # create the clang-tidy jobs, we limit ourselves to 5 threads at the moment as running clang-tidy is quite performance heavy
  threads : list[threading.Thread] = []
  threads_to_use = 5
  script_path = os.path.dirname(__file__)
  clang_tidy_path = tool_paths_dict["clang_tidy_path"]
  clang_apply_replacements_path = tool_paths_dict["clang_apply_replacements_path"]

  for compiler_db in result:
    compiler_db_folder = Path(compiler_db).parent
    config_file_path = f"{compiler_db_folder}/.clang-tidy_second_pass"

    project_name = _get_project_name_of_compdb(compiler_db_folder)
    header_filters = regis.util.retrieve_header_filters(compiler_db_folder, project_name)
    header_filters_regex = regis.util.create_header_filter_regex(header_filters)
    
    # build up the clang-tidy command
    cmd = f"py \"{script_path}/run_clang_tidy.py\""
    cmd += f" -clang-tidy-binary=\"{clang_tidy_path}\""  # location of clang-tidy executable
    cmd += f" -clang-apply-replacements-binary=\"{clang_apply_replacements_path}\"" # location of clang-apply-replacements executable
    cmd += f" -config-file=\"{config_file_path}\"" # location of clang-tidy config file
    cmd += f" -p=\"{compiler_db_folder}\"" # location of compiler db folder (not the location to the file, but to its parent folder)
    cmd += f" -header-filter={header_filters_regex}" # only care about headers of the current project
    cmd += f" -quiet" # we don't want extensive logging
    cmd += f" -j={threads_to_use}" # only use a certain amount of threads, to reduce the performance overhead

    # auto fix found issues. This doesn't work for every enabled check.
    if shouldFix:
      cmd += f" -fix"

    # add the regex of the files we care about
    cmd += f" {filesRegex}"

    # perform an incremental run, avoid rescanning previous scanned files that didn't change (ignores cpp files if their headers changed)
    if not shouldClean:
      cmd += f" -incremental"

    # dirty hack to enable single thread mode vs multi threaded mode
    # in single threaded mode, we join the threads immediately
    thread = threading.Thread(target=_run, args=(cmd,rc,))
    thread.start()

    if singleThreaded:
      thread.join()
    else:
      threads.append(thread)

  for thread in threads:
    thread.join()

  return rc[0]

def _generate_test_files(config):
  """Perform a generation for a test"""
  settings_path = os.path.join(root_path, regis.util.settingsPathFromRoot)
  build_dir = os.path.join(settings["intermediate_folder"], settings["build_folder"])
  with regis.dir_watcher.DirWatcher(build_dir, True) as dir_watcher:
    proc = regis.generation.new_generation(settings_path, config)
    proc.wait()

  return dir_watcher.created_or_modified_files

def _build_files(configs : list[str], compilers : list[str], intermediateDir : str, projectsToBuild : list[str] = "", singleThreaded : bool = False):
  """Build certain projects under a intermediate directory in certain configs using certain compilers
  This is useful after a generation to make sure all projects are build
  """

  # This is the list that'll store the results of each build
  result_arr = []

  def _run(prj, cfg, comp, intermediateDir, shouldClean, result):
    """Launch a build and store its result"""
    result.append(regis.build.new_build(prj, cfg, comp, intermediateDir, shouldClean, slnFile="", buildDependencies=True))

  should_clean = False
  intermediate_folder = settings["intermediate_folder"]
  build_folder = settings["build_folder"]

  directory = os.path.join(root_path, intermediate_folder, build_folder, intermediateDir)

  threads : list[threading.Thread] = []

  # loop over the projects, configs and compilers and create a build for each combination
  for project in projectsToBuild:
    for config in configs:
      for compiler in compilers:
        thread = threading.Thread(target=_run, args=(project, config, compiler, directory, should_clean, result_arr))
        thread.start()

        # A dirty hack for singlethreaded mode
        # we always spawn a thread but in single threaded mode, we join it immediately
        if singleThreaded:
          thread.join()
        else:
          threads.append(thread)

  # in multi threaded mode, we join threads after all of them have spawned
  for thread in threads:
    thread.join()

  # if any result return code is different than 0
  # a build has failed somewhere
  return result_arr.count(0) != len(result_arr)

def _create_full_intermediate_dir(dir):
  """Create the absolute path for the test build directory"""
  return os.path.join(os.getcwd(), settings["intermediate_folder"], settings["build_folder"], dir)

# unit tests
def _generate_unit_tests(shouldClean):
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating unit test projects")

  if shouldClean:
    # Clean the intermediates first if specified by the user
    # we clean in the generation step, to make sure that we only generate the unit tests we need
    full_intermediate_dir = _create_full_intermediate_dir(unit_tests_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  # Generate the unit test projects and return what's generated
  return _generate_test_files(regis.generation.create_config(f'-intermediate-dir={clang_tidy_intermediate_dir} -disable-clang-tidy-for-thirdparty -no-clang-tools -enable-unit-tests'))

def _build_unit_tests(projects, singleThreaded : bool = False):
  """Build the unit tests. It's assumed the unit tests are already generated"""
  task_print = regis.task_raii_printing.TaskRaiiPrint("building tests")
  return _build_files(["debug", "debug_opt", "release"], ["msvc", "clang"], unit_tests_intermediate_dir, projects, singleThreaded)

def _run_unit_tests(unitTestPrograms):
  """Run all unit tests programs that got build in an earlier step"""
  task_print = regis.task_raii_printing.TaskRaiiPrint("running unit tests")
  
  rc = 0
  
  # loop over each unit test program path and run it
  for program in unitTestPrograms:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    proc = regis.util.run_subprocess(program)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"unit test failed for {program}") # use full path to avoid ambiguity
    rc |= new_rc

  return rc

# coverage
def _generate_coverage(shouldClean):
  """Generate the projects with coverage enabled"""
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating coverage code")

  if shouldClean:
    # Clean all intermediates first if specified by the user.
    # we do this in the generation step so that we only generate coverage projects
    # for the projects that we care about
    full_intermediate_dir = _create_full_intermediate_dir(coverage_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return _generate_test_files(regis.generation.create_config(f'-intermediate-dir={coverage_intermediate_dir} -disable-clang-tidy-for-thirdparty -enable-code-coverage -enable-unit-tests'))

def _build_coverage(projects, singleThreaded : bool = False):
  """Build the projects with coverage enabled"""
  task_print = regis.task_raii_printing.TaskRaiiPrint("building coverage code")
  return _build_files(["coverage"], ["clang"], coverage_intermediate_dir, projects, singleThreaded)

def _run_coverage(unitTestPrograms):
  """Run the programs that have coverage enabled."""
  task_print = regis.task_raii_printing.TaskRaiiPrint("running coverage")

  raw_data_files = []

  rc = 0
  # LLVM uses the env variable LLVM_PROFILE_FILE
  # to hold the path where the coverage raw data should be saved to
  # running code coverage is very intensive
  # so we only allow 1 program to run at a time
  for program in unitTestPrograms:
    regis.diagnostics.log_info(f"running: {Path(program).name}")
    coverage_rawdata_filename = _get_coverage_rawdata_filename(program)
    output_path = os.path.join(Path(program).parent, coverage_rawdata_filename)
    raw_data_files.append(output_path)
    os.environ["LLVM_PROFILE_FILE"] = output_path # this is what llvm uses to set the raw data filename for the coverage data
    proc = regis.util.run_subprocess(program)
    new_rc = regis.util.wait_for_process(proc)
    if new_rc != 0:
      regis.diagnostics.log_err(f"unit test failed for {program}") # use full path to avoid ambiguity
    rc |= new_rc

  return raw_data_files

def _relocate_coverage_data(programsRun : list[str]):
  """Relocate the raw coverage data to a more appropriate location"""
  task_print = regis.task_raii_printing.TaskRaiiPrint("relocating coverage files")
  data_files = []

  for program in programsRun:
    coverage_rawdata_filename = _get_coverage_rawdata_filename(program)
    newPath = os.path.join(Path(program).parent, coverage_rawdata_filename)
    if (os.path.exists(newPath)):
      os.remove(newPath)
    os.rename(coverage_rawdata_filename, newPath)
    data_files.append(newPath)
    
  return data_files

def _index_rawdata_files(rawdataFiles : list[str]):
  task_print = regis.task_raii_printing.TaskRaiiPrint("indexing rawdata files")
  output_files = []

  for file in rawdataFiles:
    output_files.append(regis.code_coverage.create_index_rawdata(file))

  return output_files

def _create_coverage_reports(programsRun, indexdataFiles):
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

def _parse_coverage_reports(indexdataFiles):
  task_print = regis.task_raii_printing.TaskRaiiPrint("parsing coverage reports")

  rc = 0
  for indexdata_file in indexdataFiles:
    report_filename = regis.code_coverage.get_file_level_summary_filename(indexdata_file)
    rc |= regis.code_coverage.parse_file_summary(report_filename)

  return rc

def _get_coverage_rawdata_filename(program : str):
  return f"{Path(program).stem}.profraw"

# asan
def _generate_address_sanitizer(shouldClean):
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating address sanitizer code")

  if shouldClean:
    full_intermediate_dir = _create_full_intermediate_dir(asan_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return _generate_test_files(regis.generation.create_config(f'-intermediate-dir={asan_intermediate_dir} -disable-clang-tidy-for-thirdparty -enable-unit-tests -enable-address-sanitizer -IDE None'))

def _build_address_sanitizer(projects, singleThreaded : bool = False):
  task_print = regis.task_raii_printing.TaskRaiiPrint("building address sanitizer code")
  return _build_files(["address_sanitizer"], ["clang"], asan_intermediate_dir, projects, singleThreaded)

def _run_address_sanitizer(unitTestPrograms):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running address sanitizer tests")
  
  rc = 0
  for program in unitTestPrograms:
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
def _generate_undefined_behavior_sanitizer(shouldClean):
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating undefined behavior sanitizer code")

  if shouldClean:
    full_intermediate_dir = _create_full_intermediate_dir(ubsan_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return _generate_test_files(regis.generation.create_config(f'-intermediate-dir={ubsan_intermediate_dir} -disable-clang-tidy-for-thirdparty -enable-unit-tests -enable-ub-sanitizer -IDE None'))

def _build_undefined_behavior_sanitizer(projects, singleThreaded : bool = False):
  task_print = regis.task_raii_printing.TaskRaiiPrint("building undefined behavior sanitizer code")
  return _build_files(["undefined_behavior_sanitizer"], ["clang"], ubsan_intermediate_dir, projects, singleThreaded)

def _run_undefined_behavior_sanitizer(unitTestPrograms):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running undefined behavior sanitizer tests")
  
  rc = 0
  for program in unitTestPrograms:
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
def _generate_fuzzy_testing(shouldClean):
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating fuzzy testing code")

  if shouldClean:
    full_intermediate_dir = _create_full_intermediate_dir(fuzzy_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return _generate_test_files(regis.generation.create_config(f"-enable-fuzzy-testing -intermediate-dir={fuzzy_intermediate_dir} -IDE None"))

def _build_fuzzy_testing(projects, singleThreaded : bool = False):
  task_print = regis.task_raii_printing.TaskRaiiPrint("building fuzzy testing code")
  return _build_files(["fuzzy"], ["clang"], fuzzy_intermediate_dir, projects, singleThreaded)

def _run_fuzzy_testing(fuzzyPrograms):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running fuzzy tests")
  
  rc = 0
  for program in fuzzyPrograms:
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
def _generate_auto_tests(shouldClean):
  task_print = regis.task_raii_printing.TaskRaiiPrint("generating auto tests")

  if shouldClean:
    full_intermediate_dir = _create_full_intermediate_dir(auto_test_intermediate_dir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return _generate_test_files(regis.generation.create_config(f"-no-clang-tools -enable-auto-tests -intermediate-dir={auto_test_intermediate_dir} -IDE None"))

def _build_auto_tests(configs, compilers, projects, singleThreaded : bool = False):
  task_print = regis.task_raii_printing.TaskRaiiPrint("building auto tests")
  return _build_files(configs, compilers, auto_test_intermediate_dir, projects, singleThreaded)

def _process_tests_file(file, programs, timeoutInSeconds):
  json_blob = regis.rex_json.load_file(file)
    
  results = {}

  for test in json_blob:
    command_line = json_blob[test]["command_line"]

    rc = 0
    for program in programs:
      regis.diagnostics.log_info(f"running: {Path(program).name}")
      regis.diagnostics.log_info(f"with command line: {command_line}")
      proc = regis.util.run_subprocess(f"{program} {command_line}")

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
          regis.diagnostics.log_err(f"auto test timeout triggered for {program} after {max_seconds} seconds") # use full path to avoid ambiguity
        else:
          rc |= new_rc
          regis.diagnostics.log_err(f"auto test failed for {program} with returncode {new_rc}") # use full path to avoid ambiguity

      results[program] = rc

  return results

def _find_files(folder, predicate):
  found_files : list[str] = []

  for root, dirs, files in os.walk(folder):
    for file in files:
      if predicate(file):
        path = os.path.join(root, file)
        found_files.append(path)      
  
  return found_files

def _run_auto_tests(programs, timeoutInSeconds):
  task_print = regis.task_raii_printing.TaskRaiiPrint("running auto tests")
  
  test_dir = os.path.join(root_path, settings["tests_folder"])

  files = _find_files(test_dir, lambda file: Path(file).name == "tests.json")

  results : list[dict] = []

  for file in files:
    results.append(_process_tests_file(file, programs, timeoutInSeconds))

  for res in results:
    values = list(res.values())
    if (len(values) != values.count(0)):
      return 1

  return 0

# public API
def test_include_what_you_use(shouldClean : bool = True, singleThreaded : bool = False, shouldFix : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = _run_include_what_you_use(shouldFix, shouldClean, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"include-what-you-use pass failed")

  _pass_results["include-what-you-use"] = rc

def test_clang_tidy(filesRegex = ".*", shouldClean : bool = True, singleThreaded : bool = False, filterLines : bool = False, autoFix : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = _run_clang_tidy(filesRegex, shouldClean, singleThreaded, filterLines, autoFix)
  if rc != 0:
    regis.diagnostics.log_err(f"clang-tidy pass failed")

  _pass_results["clang-tidy"] = rc

def test_unit_tests(projects, shouldClean : bool = True, singleThreaded : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  generated_files = _generate_unit_tests(shouldClean)
  rc = len(generated_files) == 0
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate tests")
  _pass_results["unit tests generation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  with regis.dir_watcher.DirWatcher(_create_full_intermediate_dir(clang_tidy_intermediate_dir), True) as dir_watcher:
    rc |= _build_unit_tests(projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build tests")
  _pass_results["unit tests building"] = rc

  executables = dir_watcher.filter_created_or_modified_files(lambda dir: dir.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _run_unit_tests(executables)
  if rc != 0:
    regis.diagnostics.log_err(f"unit tests failed")
  _pass_results["unit tests result"] = rc

def test_code_coverage(projects, shouldClean : bool = True, singleThreaded : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = _generate_coverage(shouldClean)
  if not rc:
    regis.diagnostics.log_err(f"failed to generate coverage")
  # _pass_results stores return codes
  # so we need store 0 for success, anything else for failure
  _pass_results["coverage generation"] = len(rc) == 0

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc = _build_coverage(projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build coverage")
  _pass_results["coverage building"] = rc

  executables = _find_files(_create_full_intermediate_dir(coverage_intermediate_dir), lambda file: file.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rawdata_files = _run_coverage(executables)
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  indexdata_files = _index_rawdata_files(rawdata_files)
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _create_coverage_reports(executables, indexdata_files)
  if rc != 0:
    regis.diagnostics.log_err(f"failed to create coverage reports")
  _pass_results["coverage report creation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _parse_coverage_reports(indexdata_files)
  if rc != 0:
    regis.diagnostics.log_err(f"Not all the code was covered")
  _pass_results["coverage report result"] = rc

def test_asan(projects, shouldClean : bool = True, singleThreaded : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  generated_files = _generate_address_sanitizer(shouldClean)
  rc = len(generated_files) == 0
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate asan code")
  _pass_results["address sanitizer generation"] = rc

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _build_address_sanitizer(projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build asan code")
  _pass_results["address sanitizer building"] = rc
  
  executables = _find_files(_create_full_intermediate_dir(asan_intermediate_dir), lambda file: file.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _run_address_sanitizer(executables)
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with asan")
  _pass_results["address sanitizer result"] = rc

def test_ubsan(projects, shouldClean : bool = True, singleThreaded : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  generated_files = _generate_undefined_behavior_sanitizer(shouldClean)
  rc = len(generated_files) == 0
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate ubsan code")
  _pass_results["undefined behavior sanitizer generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  with regis.dir_watcher.DirWatcher('.', True) as dir_watcher:
    rc |= _build_undefined_behavior_sanitizer(projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build ubsan code")
  _pass_results["undefined behavior sanitizer building"] = rc
  
  executables = _find_files(_create_full_intermediate_dir(ubsan_intermediate_dir), lambda file: file.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _run_undefined_behavior_sanitizer(executables)
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with ubsan")
  _pass_results["undefined behavior sanitizer result"] = rc

def test_fuzzy_testing(projects, shouldClean : bool = True, singleThreaded : bool = False):
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  generated_files = _generate_fuzzy_testing(shouldClean)
  rc = len(generated_files) == 0

  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate fuzzy code")
  _pass_results["fuzzy testing generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  with regis.dir_watcher.DirWatcher('.', True) as dir_watcher:
    rc |= _build_fuzzy_testing(projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build fuzzy code")
  _pass_results["fuzzy testing building"] = rc

  executables = _find_files(_create_full_intermediate_dir(fuzzy_intermediate_dir), lambda file: file.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _run_fuzzy_testing(executables)
  if rc != 0:
    regis.diagnostics.log_err(f"invalid code found with fuzzy")
  _pass_results["fuzzy testing result"] = rc

def run_auto_tests(configs, compilers, projects, timeoutInSeconds : int, shouldClean : bool = True, singleThreaded : bool = False):
  rc = 0

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  generated_files = _generate_auto_tests(shouldClean)
  rc = len(generated_files) == 0
  
  if rc != 0:
    regis.diagnostics.log_err(f"failed to generate auto test code")
  _pass_results["auto testing generation"] = rc
  
  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  with regis.dir_watcher.DirWatcher('.', True) as dir_watcher:
    rc |= _build_auto_tests(configs, compilers, projects, singleThreaded)

  if rc != 0:
    regis.diagnostics.log_err(f"failed to build auto test code")
  _pass_results["auto testing building"] = rc
  
  executables = _find_files(_create_full_intermediate_dir(auto_test_intermediate_dir), lambda file: file.endswith('.exe'))

  regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
  rc |= _run_auto_tests(executables, timeoutInSeconds)
  if rc != 0:
    regis.diagnostics.log_err(f"auto tests failed")
  _pass_results["auto testing result"] = rc
