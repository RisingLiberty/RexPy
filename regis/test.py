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
import shutil
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
from requests.structures import CaseInsensitiveDict
from enum import Enum, auto

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
  logs_dir = os.path.join(settings["intermediate_folder"], settings["logs_folder"])
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

def _get_coverage_rawdata_filename(program : str):
  return f"{Path(program).stem}.profraw"

def _create_coverage_report(program, indexedFile):
  with regis.task_raii_printing.TaskRaiiPrint("creating coverage reports"):

    if Path(program).stem != Path(indexedFile).stem:
      regis.diagnostics.log_err(f"program stem doesn't match coverage file stem: {Path(program).stem} != {Path(indexedFile).stem}")
      return 1

    regis.code_coverage.create_line_oriented_report(program, indexedFile)
    regis.code_coverage.create_file_level_summary(program, indexedFile)
    regis.code_coverage.create_lcov_report(program, indexedFile)

  return 0

def _parse_coverage_report(indexedFile):
  with regis.task_raii_printing.TaskRaiiPrint("parsing coverage reports"):
      report_filename = regis.code_coverage.get_file_level_summary_filename(indexedFile)
      return regis.code_coverage.parse_file_summary(report_filename)

class RunnableType(Enum):
  Default = 0,
  Coverage = auto(),
  Sanitizer = auto(),

class Runnable():
  def __init__(self, runnableDict, args = [], enableAsan : bool = False, enableUbsan : bool = False):
    self.program = runnableDict['Program']
    self.type = RunnableType[runnableDict['RunnableType']]
    self.args = args
    self.proc = None
    self.terminated = False
    self.finished = False
    self.enable_asan = enableAsan
    self.enable_ubsan = enableUbsan
  
  def run(self):
    regis.diagnostics.log_info(f"running: {Path(self.program).name}")
    regis.diagnostics.log_info(f"with args: {self.args}")

    # error code by default in case we don't trigger any runnable
    rc = 1

    if self.type == RunnableType.Default:
      rc = self._default_run()
    
    if self.type == RunnableType.Coverage:
      rc = self._run_coverage()
    
    if self.type == RunnableType.Sanitizer:
      rc = self._run_sanitizer()
            
    self.finished = True
    return rc

  def terminate(self):
    if self.proc:
      self.proc.terminate()

    self.terminated = True
    self.finished = True

  def _default_run(self):
    self.proc = regis.util.run_subprocess(self.program, self.args)
    return regis.util.wait_for_process(self.proc)

  def _run_coverage(self):
    # First run the program
    coverage_rawdata_filename = _get_coverage_rawdata_filename(self.program)
    raw_data_file = os.path.join(Path(self.program).parent, coverage_rawdata_filename)
    os.environ["LLVM_PROFILE_FILE"] = raw_data_file # this is what llvm uses to set the raw data filename for the coverage data
    self.proc = regis.util.run_subprocess(self.program, self.args)
    rc = regis.util.wait_for_process(self.proc)

    # Then index the raw data file
    indexed_file = regis.code_coverage.create_index_rawdata(raw_data_file)

    # next create the coverage report
    rc |= _create_coverage_report(self.program, indexed_file)

    # finally, parse the coverage report
    rc |= _parse_coverage_report(indexed_file)

    return rc
  
  def _run_sanitizer(self):
    rc = 0

    # ASAN_OPTIONS common flags: https://github.com/google/sanitizers/wiki/SanitizerCommonFlags
    # ASAN_OPTIONS flags: https://github.com/google/sanitizers/wiki/AddressSanitizerFlags
    # UBSAN_OPTIONS common flags: https://github.com/google/sanitizers/wiki/SanitizerCommonFlags
    log_folder = os.path.join(root_path, settings["intermediate_folder"], settings["logs_folder"])
    
    if self.enable_asan:
      asan_log_path = os.path.join(log_folder, 'asan.log').replace('\\', '/')
      asan_options = f"print_stacktrace=1:log_path=\"{asan_log_path}\""
      os.environ["ASAN_OPTIONS"] = asan_options # print callstacks and save to log file

    if self.enable_ubsan:
      ubsan_log_path = os.path.join(log_folder, 'ubsan.log').replace('\\', '/')
      ubsan_options = f"print_stacktrace=1:log_path=\"{ubsan_log_path}\""
      os.environ["UBSAN_OPTIONS"] = ubsan_options # print callstacks and save to log file
    
    self.proc = regis.util.run_subprocess(self.program, self.args)
    new_rc = regis.util.wait_for_process(self.proc)
    if new_rc != 0 or os.path.exists(asan_log_path) or os.path.exists(ubsan_log_path):
      regis.diagnostics.log_err(f"sanitization failed for {self.program}") # use full path to avoid ambiguity
      regis.diagnostics.log_err(f"for more info regarding asan, please check: {asan_log_path}")
      regis.diagnostics.log_err(f"for more info regarding ubsan, please check: {ubsan_log_path}")
      new_rc = 1
    rc |= new_rc

    return rc

# ---------------------------------------------
# Code Analysis jobs
# ---------------------------------------------

class IncludeWhatYouUseJob():
  """A job that runs include-what-you-use over a project"""
  def __init__(self, shouldClean : bool, fixIncludes : bool):
    self.should_clean = shouldClean
    self.fix_includes = fixIncludes
    return
  
  def execute(self, singleThreaded : bool):
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc = self._generate()
    _pass_results["include-what-you-use generate"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"include-what-you-use generation failed")
      return rc

    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc = self._run(singleThreaded)
    _pass_results["include-what-you-use run"] = rc

    if rc != 0:
      regis.diagnostics.log_err(f"include-what-you-use pass failed")
      return rc
    
    return rc
  
  def _generate(self):
    """Generate the projects to run include-what-you-use on"""
    config = regis.generation.create_config(f'-intermediate-dir={iwyu_intermediate_dir} -enable-clang-tools -disable-clang-tidy-for-thirdparty')
    return _generate_test_files(self.should_clean, iwyu_intermediate_dir, config)
  
  def _run(self, singleThreaded : bool):
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
  
    with regis.task_raii_printing.TaskRaiiPrint("running include-what-you-use"):
      # find all the compiler dbs.
      # these act as input for include-what-you-use
      intermediate_folder = os.path.join(root_path, settings["intermediate_folder"], settings["build_folder"], iwyu_intermediate_dir)
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
      if self.fix_includes:
        regis.diagnostics.log_info(f'Applying fixes..')

      fix_includes_path = os.path.join(Path(iwyu_path).parent, "fix_includes.py")

      # this is the actual run in trying to fix the includes
      # however it can be faked when self.fix_includes is false
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

        if self.fix_includes == False:
          cmd += f" --dry_run"

        # run the fix includes command line
        rc |= os.system(f"{cmd}")  

      return rc

class ClangTidyJob():
  """A job that runs clang-tidy over a project"""
  def __init__(self, shouldClean : bool, autoFix : bool, filterLines : bool, filesRegex : str):
    self.should_clean = shouldClean
    self.auto_fix = autoFix
    self.filter_lines = filterLines
    self.files_regex = filesRegex
    return
  
  def execute(self, singleThreaded : bool):
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc = self._generate()
    _pass_results["clang-tidy generation"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"clang-tidy pass failed")
      return rc

    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc = self._run(self.filter_lines, singleThreaded)
    _pass_results["clang-tidy run"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"clang-tidy pass failed")
      return rc

    return rc

  def _generate(self):
    config = regis.generation.create_config(f'-intermediate-dir={clang_tidy_intermediate_dir} -enable-clang-tools -disable-clang-tidy-for-thirdparty')
    return _generate_test_files(self.should_clean, clang_tidy_intermediate_dir, config)
    
  def _run(self, filterLines : bool, singleThreaded : bool):
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

    with regis.task_raii_printing.TaskRaiiPrint("running clang-tidy"):

      # get the compiler dbs that are just generated
      result = _find_files(_create_full_intermediate_dir(clang_tidy_intermediate_dir), lambda file: 'compile_commands.json' in file)

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
        if self.auto_fix:
          cmd += f" -fix"

        # add the regex of the files we care about
        cmd += f" {self.files_regex}"

        # perform an incremental run, avoid rescanning previous scanned files that didn't change (ignores cpp files if their headers changed)
        if not self.should_clean:
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

# ---------------------------------------------
# Unit Tests
# ---------------------------------------------
#
# Supports asan, ubsan and code coverage
#
class UnitTestJob():
  """A job that runs unit test projects"""
  def __init__(self, projects : list[str], shouldClean : bool, enableAsan : bool, enableUbsan : bool, enableCodeCoverage : bool):
    self.projects = projects
    self.enable_asan = enableAsan
    self.enable_ubsan = enableUbsan
    self.enable_code_coverage = enableCodeCoverage
    self.should_clean = shouldClean
  
  def execute(self, singleThreaded : bool):
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")

    # Generate the unit tests
    rc = self._generate()
    _pass_results["unit tests generation"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"failed to generate tests")
      return rc

    # pull out the generated projects, so we know what we can build and run
    test_projects_path = os.path.join(root_path, settings['intermediate_folder'], settings['build_folder'], 'test_projects.json')
    if not os.path.exists(test_projects_path):
      regis.diagnostics.log_err(f'"{test_projects_path}" does not exist.')
      return rc | 1

    # if no projects are specified, we run on all of them
    test_projects = regis.rex_json.load_file(test_projects_path)
    unit_test_projects = CaseInsensitiveDict(test_projects["TypeSettings"].get("UnitTest"))

    self.projects = self.projects or list(unit_test_projects.keys())

    # If we still have no projects, generation silently failed.
    # either way, we need to exit here
    if not self.projects:
      regis.diagnostics.log_warn(f'No unit test projects found. have you generated them?')
      _pass_results["unit tests - nothing to do"] = rc
      return rc

    # Now build the projects we're interested in
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc |= self._build(self.projects, singleThreaded)

    # if any builds fail, we can't run any tests
    # so we exit here
    _pass_results["unit tests building"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"failed to build tests")
      return rc

    # Now that we've build everything, let's run everything
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    for project in self.projects:
      if project not in unit_test_projects:
        regis.diagnostics.log_err(f'project "{project}" not found in {test_projects_path}. Please check its generation settings')
        continue

      # get the project test settings out of our testing files
      project_settings = unit_test_projects[project]
      runnables = project_settings['TargetRunnables']
      working_dir = project_settings['WorkingDir']
      
      # run all the tests
      rc = self._run(runnables, working_dir)
      _pass_results[f"unit tests result - {project}"] = rc

    # Report any issues
    if rc != 0:
      regis.diagnostics.log_err(f"unit tests failed")
      return rc
    
    return rc    

  def _generate(self):
    with regis.task_raii_printing.TaskRaiiPrint("generating unit test projects"):
      config_args = []
      config_args.append(f'-intermediate-dir={unit_tests_intermediate_dir}')
      config_args.append('-disable-clang-tidy-for-thirdparty')
      config_args.append('-enable-unit-tests')
      config_args.append('-disable-default-generation')

      if self.enable_code_coverage:
        config_args.append('-enable-code-coverage')
        config_args.append('-disable-default-configs')

      if self.enable_asan:
        config_args.append('-enable-address-sanitizer')
        config_args.append('-disable-default-configs')

      if self.enable_ubsan:
        config_args.append('-enable-ub-sanitizer')
        config_args.append('-disable-default-configs')

      config = regis.generation.create_config(' '.join(config_args))
      return _generate_test_files(self.should_clean, unit_tests_intermediate_dir, config)
  
  def _build(self, projects : list[str], singleThreaded : bool):
    with regis.task_raii_printing.TaskRaiiPrint("building unit tests"):
      return _build_files(projects, singleThreaded)
  
  def _run(self, runnables : list, workingDir : str):
    with regis.task_raii_printing.TaskRaiiPrint("running unit tests"):
      with regis.util.temp_cwd(workingDir):
        rc = 0
    
        # loop over each unit test program path and run it
        for runnable_dict in runnables:
          runnable = Runnable(runnable_dict, [], self.enable_asan, self.enable_ubsan)
          new_rc = runnable.run()

          if new_rc != 0:
            regis.diagnostics.log_err(f"unit test failed for {runnable.program}") # use full path to avoid ambiguity
          rc |= new_rc

        return rc

# ---------------------------------------------
# Auto Tests
# ---------------------------------------------
#
# Supports asan, ubsan and code coverage
#

class AutoTestJob():
  """A job that runs auto tests"""
  def __init__(self, projects : list[str], timeoutInSeconds : int, shouldClean : bool, enableAsan : bool, enableUbsan : bool, enableCodeCoverage : bool):
    self.projects = projects
    self.enable_asan = enableAsan
    self.enable_ubsan = enableUbsan
    self.enable_code_coverage = enableCodeCoverage
    self.should_clean = shouldClean
    self.timeout_in_seconds = timeoutInSeconds
  
  def execute(self, singleThreaded : bool):
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")

    # Generate the unit tests
    rc = self._generate()
    _pass_results["auto testing generation"] = rc
    
    if rc != 0:
      regis.diagnostics.log_err(f"failed to generate auto test code")
      return rc
    
    # pull out the generated projects, so we know what we can build and run
    test_projects_path = os.path.join(root_path, settings['intermediate_folder'], settings['build_folder'], 'test_projects.json')
    if not os.path.exists(test_projects_path):
      regis.diagnostics.log_err(f'"{test_projects_path}" does not exist.')
      return rc | 1

    # if no projects are specified, we run on all of them
    test_projects = regis.rex_json.load_file(test_projects_path)
    auto_test_projects = CaseInsensitiveDict(test_projects["TypeSettings"].get("AutoTest"))

    self.projects = self.projects or list(auto_test_projects.keys())

    # If we still have no projects, generation silently failed.
    # either way, we need to exit here
    if not self.projects:
      regis.diagnostics.log_warn(f'No auto test projects found. have you generated them?')
      _pass_results["auto testing - nothing to do"] = rc
      return rc

    # Now build the projects we're interested in
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc |= self._build(self.projects, singleThreaded)

    # if any builds fail, we can't run any tests
    # so we exit here
    _pass_results["auto testing building"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"failed to build auto test code")
      return rc
    
    # Now that we've build everything, let's run everything
    for project in self.projects:
      if project not in auto_test_projects:
        regis.diagnostics.log_err(f'project "{project}" not found in {test_projects_path}. Please check its generation settings')
        continue

      # get the project test settings out of our testing files
      project_settings = auto_test_projects[project]
      runnables = project_settings['TargetRunnables']
      working_dir = project_settings['WorkingDir']
      test_file = _find_tests_file(project_settings)

      # run all the tests
      new_rc = self._run(runnables, working_dir, test_file, self.timeout_in_seconds)
      _pass_results[f'auto tests result - {project}'] = new_rc

      rc |= new_rc

    # report any issues
    if rc != 0:
      regis.diagnostics.log_err(f"auto tests failed")
      return rc

    return rc
  
  def _generate(self):
    with regis.task_raii_printing.TaskRaiiPrint("generating auto tests"):
      config_args = []
      config_args.append(f'-intermediate-dir={auto_test_intermediate_dir}')
      config_args.append('-enable-auto-tests')
      config_args.append('-disable-default-generation')

      if self.enable_code_coverage:
        config_args.append('-enable-code-coverage')
        config_args.append('-disable-default-configs')

      if self.enable_asan:
        config_args.append('-enable-address-sanitizer')
        config_args.append('-disable-default-configs')

      if self.enable_ubsan:
        config_args.append('-enable-ub-sanitizer')
        config_args.append('-disable-default-configs')

      config = regis.generation.create_config(' '.join(config_args))
      return _generate_test_files(self.should_clean, auto_test_intermediate_dir, config)
  
  def _build(self, projects : list[str], singleThreaded : bool):
    return _build_files(projects, singleThreaded)
  
  def _run(self, runnables : list[str], workingDir : str, testFilePath : str, timeoutInSeconds : int):
    json_blob = regis.rex_json.load_file(testFilePath)

    with regis.task_raii_printing.TaskRaiiPrint("running auto tests"):
      with regis.util.temp_cwd(workingDir):
        rc = 0

        for test in json_blob:
          command_line : str = json_blob[test]["command_line"]
          now = time.time()
          max_seconds = timeoutInSeconds
          def monitor_runnable(runnable : Runnable):
            while not runnable.finished:
              duration = time.time() - now
              if duration > max_seconds:
                runnable.terminate()

              time.sleep(1)

          # loop over each unit test program path and run it
          for runnable_dict in runnables:
            runnable = Runnable(runnable_dict, command_line, self.enable_asan, self.enable_ubsan)
            thread = threading.Thread(target=monitor_runnable, args=(runnable,))
            thread.start()

            new_rc = runnable.run()
            thread.join()

            if new_rc != 0:
              if runnable.terminated:
                regis.diagnostics.log_err(f"auto test timeout triggered for {runnable.program} after {max_seconds} seconds") # use full path to avoid ambiguity
              else:
                rc |= new_rc
                regis.diagnostics.log_err(f"auto test failed for {runnable.program} with returncode {new_rc}") # use full path to avoid ambiguity
          
        return rc
  
# ---------------------------------------------
# Fuzzy Tests
# ---------------------------------------------
#
# Supports asan, ubsan and code coverage
#

class FuzzyTestJob():
  """A job that runs fuzzy tests"""
  def __init__(self, projects : list[str], numRums : int, shouldClean : bool, enableAsan : bool, enableUbsan : bool, enableCodeCoverage : bool):
    self.projects = projects
    self.enable_asan = enableAsan
    self.enable_ubsan = enableUbsan
    self.enable_code_coverage = enableCodeCoverage
    self.should_clean = shouldClean
    self.num_runs = numRums
  
  def execute(self, singleThreaded : bool):
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    
    # Generate the fuzzy tests
    rc = self._generate()
    _pass_results["fuzzy testing generation"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"failed to generate fuzzy code")
      return rc

    # pull out the generated projects, so we know what we can build and run
    test_projects_path = os.path.join(root_path, settings['intermediate_folder'], settings['build_folder'], 'test_projects.json')
    if not os.path.exists(test_projects_path):
      regis.diagnostics.log_err(f'"{test_projects_path}" does not exist.')
      return rc | 1

    # if no projects are specified, we run on all of them
    test_projects = regis.rex_json.load_file(test_projects_path)
    fuzzy_test_projects = CaseInsensitiveDict(test_projects["TypeSettings"].get("Fuzzy"))

    self.projects = self.projects or list(fuzzy_test_projects.keys())

    # If we still have no projects, generation silently failed.
    # either way, we need to exit here
    if not self.projects:
      regis.diagnostics.log_warn(f'No fuzzy test projects found. have you generated them?')
      _pass_results["fuzzy testing - nothing to do"] = rc
      return rc

    # Now build the projects we're interested in
    regis.diagnostics.log_no_color("-----------------------------------------------------------------------------")
    rc |= self._build(self.projects, singleThreaded)

    # if any builds fail we can't run any tests
    # so we exit here
    _pass_results["fuzzy testing building"] = rc
    if rc != 0:
      regis.diagnostics.log_err(f"failed to build fuzzy code")
      return rc

    # Now that we've build everything, let's run everything
    for project in self.projects:
      if project not in fuzzy_test_projects:
        regis.diagnostics.log_err(f'project "{project}" not found in {test_projects_path}. Please check its generation settings')
        continue

      # get the project test settings out of our testing files
      project_settings = fuzzy_test_projects[project]
      runnables = project_settings['TargetRunnables']
      working_dir = project_settings['WorkingDir']

      # run all the tests
      new_rc = self._run(runnables, working_dir)
      _pass_results[f'fuzzy tests result - {project}'] = rc

      rc |= new_rc

    # report any issues
    if rc != 0:
      regis.diagnostics.log_err('fuzzy tests failed')
      return rc
    
    return rc

  def _generate(self):
    with regis.task_raii_printing.TaskRaiiPrint("generating fuzzy testing code"):

      config_args = []
      config_args.append(f'-intermediate-dir={fuzzy_intermediate_dir}')
      config_args.append('-enable-fuzzy-testing')
      config_args.append('-disable-default-configs')

      if self.enable_code_coverage:
        config_args.append('-enable-code-coverage')

      if self.enable_asan:
        config_args.append('-enable-address-sanitizer')

      if self.enable_ubsan:
        config_args.append('-enable-ub-sanitizer')

      config = regis.generation.create_config(' '.join(config_args))
      return _generate_test_files(self.should_clean, fuzzy_intermediate_dir, config)
  
  def _build(self, projects : list[str], singleThreaded : bool):
    with regis.task_raii_printing.TaskRaiiPrint("building unit tests"):
      return _build_files(projects, singleThreaded)
  
  def _run(self, runnables : list, workingDir : str):
     with regis.task_raii_printing.TaskRaiiPrint("running unit tests"):
      with regis.util.temp_cwd(workingDir):

        rc = 0
    
        # loop over each unit test program path and run it
        for runnable_dict in runnables:
          args = []
          args.append('corpus')
          args.append(f'-runs={self.num_runs}')
          runnable = Runnable(runnable_dict, args, self.enable_asan, self.enable_ubsan)
          new_rc = runnable.run()

          if new_rc != 0:
            regis.diagnostics.log_err(f"fuzzy testing failed for {runnable.program}") # use full path to avoid ambiguity

          rc |= new_rc

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

def _find_files(folder, predicate):
  found_files : list[str] = []

  for root, dirs, files in os.walk(folder):
    for file in files:
      if predicate(file):
        path = os.path.join(root, file)
        found_files.append(path)      
  
  return found_files

def _generate_test_files(shouldClean : bool, intermediateDir : str, config):
  """Perform a generation for a test"""
  if shouldClean:
    # Clean the intermediates first if specified by the user
    # we clean in the generation step, to make sure that we only generate the unit tests we need
    full_intermediate_dir = _create_full_intermediate_dir(intermediateDir)
    regis.diagnostics.log_info(f"cleaning {full_intermediate_dir}..")
    regis.util.remove_folders_recursive(full_intermediate_dir)

  return regis.generation.new_generation(settings, config)

def _build_files(projectsToBuild : list[str] = "", singleThreaded : bool = False):
  """Build certain projects under a intermediate directory in certain configs using certain compilers
  This is useful after a generation to make sure all projects are build
  """

  res = 0

  # loop over the projects create a build for each combination
  for project in projectsToBuild:
    res |= regis.build.build_all(project, shouldBuild=True, shouldClean=False, buildDependencies=True, singleThreaded=singleThreaded)

  return res

def _create_full_intermediate_dir(dir):
  """Create the absolute path for the test build directory"""
  return os.path.join(os.getcwd(), settings["intermediate_folder"], settings["build_folder"], dir)

def _find_tests_file(projectSettings : dict):
  project_root = projectSettings["Root"]
  test_file_path = os.path.join(project_root, "tests.json")

  if not os.path.exists(test_file_path):
    return None

  return test_file_path

# public API
def test_include_what_you_use(shouldClean : bool = True, singleThreaded : bool = False, shouldFix : bool = False):
  iwyu_job = IncludeWhatYouUseJob(shouldClean, shouldFix)
  return iwyu_job.execute(singleThreaded)
  
def test_clang_tidy(filesRegex = ".*", shouldClean : bool = True, singleThreaded : bool = False, filterLines : bool = False, autoFix : bool = False):
  clang_tidy_job = ClangTidyJob(shouldClean, autoFix, filterLines, filesRegex)
  return clang_tidy_job.execute(singleThreaded)

def test_unit_tests(projects, shouldClean : bool = True, singleThreaded : bool = False, enableAsan : bool = False, enableUbsan : bool = False, enableCoverage : bool = False):
  unit_test_job = UnitTestJob(projects, shouldClean, enableAsan, enableUbsan, enableCoverage)
  return unit_test_job.execute(singleThreaded)

def test_fuzzy_testing(projects, numRuns, shouldClean : bool = True, singleThreaded : bool = False, enableAsan : bool = False, enableUbsan : bool = False, enableCodeCoverage : bool = False):
  fuzzy_test_job = FuzzyTestJob(projects, numRuns, shouldClean, enableAsan, enableUbsan, enableCodeCoverage)
  return fuzzy_test_job.execute(singleThreaded)
  
def run_auto_tests(projects, timeoutInSeconds : int, shouldClean : bool = True, singleThreaded : bool = False, enableAsan : bool = False, enableUbsan : bool = False, enableCodeCoverage : bool = False):
  auto_test_job = AutoTestJob(projects, timeoutInSeconds, shouldClean, enableAsan, enableUbsan, enableCodeCoverage)
  return auto_test_job.execute(singleThreaded)

# Creating new projects
class TestProjectType(Enum):
  UnitTest = 0,
  AutoTest = auto(),
  FuzzyTest = auto(),

def create_new_project(solutionFolder : str, project : str, projectType : TestProjectType):
  if projectType == TestProjectType.UnitTest:
    sharpmake_file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_unit_test_template.sharpmake.cs')
    file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_unit_test_template.cpp')
  if projectType == TestProjectType.FuzzyTest:
    sharpmake_file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_fuzzy_test_template.sharpmake.cs')
    file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_fuzzy_test_template.cpp')
  if projectType == TestProjectType.AutoTest:
    sharpmake_file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_auto_test_template.sharpmake.cs')
    file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_auto_test_entry_template.cpp')

  # first make the directory that'll hold all the project's source files
  project_folder = regis.util.to_snakecase(project)
  project = regis.util.to_camelcase(project)
  project_dir = os.path.join(root_path, 'tests', solutionFolder, project_folder)
  if os.path.isdir(project_dir):
    regis.diagnostics.log_err(f'project directory "{project_dir}" already exists.')
    return

  os.makedirs(project_dir)
  regis.diagnostics.log_info(f'project dir created at {project_dir}')

  # create the sub directories for the source files
  os.mkdir(os.path.join(project_dir, 'include'))
  os.mkdir(os.path.join(project_dir, 'config'))
  os.mkdir(os.path.join(project_dir, 'src'))

  # create the sharpmake file
  test_sharpmake_file = os.path.join(project_dir, f'{project_folder}.sharpmake.cs')
  sharpmake_content = open(sharpmake_file_template).read()
  sharpmake_content = sharpmake_content.replace('<UnitTestProjectName>', project)
  sharpmake_content = sharpmake_content.replace('<test_solution_folder>', solutionFolder)
  open(test_sharpmake_file, 'w').write(sharpmake_content)

  # copy the test template
  test_file = os.path.join(project_dir, 'src', f'{project_folder}.cpp')
  shutil.copy(file_template, test_file)  

  # for auto tests we need to copy a template of an auto test file as well
  if projectType == TestProjectType.AutoTest:
    file_template = os.path.join(root_path, '_build', 'sharpmake', 'templates', 'rex_auto_test_template.cpp')
    auto_test_file = os.path.join(project_dir, 'src', f'{project_folder}_test.cpp')
    shutil.copy(file_template, auto_test_file)  
