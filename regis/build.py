import os
import threading
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc
import regis.dir_watcher
import regis.generation

from pathlib import Path

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict
root = regis.util.find_root()  
settings_path = os.path.join(root, regis.util.settingsPathFromRoot)
settings = regis.rex_json.load_file(settings_path)
intermediate_path = os.path.join(root, settings['intermediate_folder'], settings['build_folder'])
build_projects_path = os.path.join(intermediate_path, settings['build_projects_filename'])

class NinjaProject:
  def __init__(self, filepath : str):
    self.json_blob : dict = regis.rex_json.load_file(filepath)
    self.filepath = filepath
    self.project_name = self.json_blob['name']

  def ninja_file(self, compiler : str, config : str):
    return self.json_blob['configs'][compiler.lower()][config.lower()]["ninja_file"]

  def dependencies(self, compiler : str, config : str):
    return self.json_blob['configs'][compiler.lower()][config.lower()]["dependencies"]

  def clean(self, compiler : str, config : str, buildDependencies : bool, verboseOutput = False):
    ninja_path = tool_paths_dict["ninja_path"]
    regis.diagnostics.log_info(f'Cleaning intermediates')
    
    r = self._valid_args_check(compiler, config)
    if r != 0:
      return r

    if buildDependencies:
      self._clean_dependencies(compiler, config, verboseOutput)

    cmd = f"{ninja_path} -f {self.ninja_file(compiler, config)} -t clean"

    if verboseOutput:
      cmd += ' -v'

    proc = regis.subproc.run(cmd)
    proc.wait()

    r = proc.returncode
    return r
  
  def build(self, compiler : str, config : str, buildDependencies : bool, verboseOutput = False):
    r = 0

    r = self._valid_args_check(compiler, config)
    if r != 0:
      return r

    # make sure to build the dependencies first
    if buildDependencies:
      r |= self._build_dependencies(compiler, config, verboseOutput)

    regis.diagnostics.log_info(f"Building: {self.project_name} - {config} - {compiler}")

    # then build the project we specified
    ninja_path = tool_paths_dict["ninja_path"]
    cmd = f"{ninja_path} -f {self.ninja_file(compiler, config)}"

    if verboseOutput:
      cmd += ' -v'

    regis.diagnostics.log_info(f'executing: {cmd}')
    proc = regis.subproc.run(cmd)
    proc.wait()
    r |= proc.returncode

    # show error if any build failed
    if r != 0:
      regis.diagnostics.log_err(f"Failed to build {self.project_name}")

    return r
  
  def rebuild(self, compiler : str, config : str, buildDependencies : bool):
    r = self.clean(compiler, config, buildDependencies)
    if r != 0:
      return r
    
    r = self.build(compiler, config, buildDependencies)

    return r
   
  def _valid_args_check(self, compiler : str, config : str):
    if compiler not in self.json_blob['configs']:
      regis.diagnostics.log_err(f"no compiler '{compiler}' found for project '{self.project_name}'")
      regis.diagnostics.log_err('Found compilers are')
      for compiler_name in self.json_blob['configs']:
        regis.diagnostics.log_err(f'- {compiler_name}')
      return 1
  
    if config not in self.json_blob['configs'][compiler]:
      regis.diagnostics.log_err(f"error in {self.filepath}")
      regis.diagnostics.log_err(f"no config '{config}' found in project '{self.project_name}' for compiler '{compiler}'")
      regis.diagnostics.log_err('Found configs are')
      for config_name in self.json_blob['configs'][compiler]:
        regis.diagnostics.log_err(f'- {config_name}')
      return 1
    
    return 0

  def _build_dependencies(self, compiler, config, verboseOutput):
    dependencies = self.json_blob['configs'][compiler][config]["dependencies"]

    r = 0
    for dependency in dependencies:      
      dependency_project_name = Path(dependency).stem
      regis.diagnostics.log_info(f'Building dependency: {self.project_name} -> {dependency_project_name}')

      dependency_project = NinjaProject(dependency)
      r |= dependency_project.build(compiler, config, buildDependencies=True, verboseOutput=verboseOutput)

    return r

  def _clean_dependencies(self, compiler, config, verboseOutput):
    dependencies = self.json_blob['configs'][compiler][config]["dependencies"]

    r = 0
    for dependency in dependencies:      
      dependency_project_name = Path(dependency).stem
      regis.diagnostics.log_info(f'Building dependency: {self.project_name} -> {dependency_project_name}')

      dependency_project = NinjaProject(dependency)
      r |= dependency_project.clean(compiler, config, buildDependencies=True, verboseOutput=verboseOutput)

    return r

  def compilers(self):
    return self.json_blob['configs']

def find_sln(directory):
  """Find the ninja solution in the specified directory"""
  dirs = os.listdir(directory)

  res = []

  for dir in dirs:
    full_path = os.path.join(directory, dir)
    if os.path.isfile(full_path) and Path(full_path).suffix == ".nsln":
      res.append(full_path)
    
  return res

def _find_ninja_project_file(slnFile : str, projectName : str):
  sln_jsob_blob = CaseInsensitiveDict(regis.rex_json.load_file(slnFile))
  
  if projectName not in sln_jsob_blob:
    regis.diagnostics.log_err(f"project '{projectName}' was not found in solution, have you generated it?")
    regis.diagnostics.log_err(f'found projects are')
    for project in sln_jsob_blob:
      regis.diagnostics.log_err(f'- {project}')
    return None
  
  project_file_path = sln_jsob_blob[projectName]    
  return NinjaProject(project_file_path)

def _launch_new_build(project : NinjaProject, config : str, compiler : str, shouldBuild : bool, shouldClean : bool, buildDependencies = False, verboseOutput = False):
  """Load the solution, look for the project in the solution and build it"""
  compiler_lower = compiler.lower()
  config_lower = config.lower()

  r = 0

  if shouldClean:
    r |= project.clean(compiler_lower, config_lower, buildDependencies, verboseOutput)

  if shouldBuild:
    r |= project.build(compiler_lower, config_lower, buildDependencies, verboseOutput)

  return r

def _look_for_sln_file_to_use(slnFile : str):
  """Look for the specified sln. Look for a sln in the root if no solution path is specified."""
  if slnFile == "":
    root = regis.util.find_root()
    sln_files = find_sln(root)

    if len(sln_files) > 1:
      regis.diagnostics.log_err(f'more than 1 nsln file was found in the cwd, please specify which one you want to use')
    
      for file in sln_files:
        regis.diagnostics.log_err(f'-{file}')
    
      return ""
    
    if len(sln_files) == 0:
      regis.diagnostics.log_err(f'no nlsn found in {root}')
      return ""

    slnFile = sln_files[0]
  elif not os.path.exists(slnFile):
    regis.diagnostics.log_err(f'solution path {slnFile} does not exist')
    return ""
  
  return slnFile

def _update_cleaned_projects(project : str, config : str, compiler : str, deletedProgram : str):
  """Update the build projects file and remove all the projects that have been cleaned"""
  build_projects = regis.rex_json.load_file(build_projects_path)

  project = project.lower()
  config = config.lower()
  compiler = compiler.lower()

  if project not in build_projects:
    return
  
  build_project = build_projects[project]
  if config not in build_project:
    return
  
  build_config = build_projects[project][config]
  if compiler not in build_config:
    return
  
  build_programs : list[str] = build_projects[project][config][compiler]

  if deletedProgram in build_programs:
    build_programs.remove(deletedProgram)

  regis.rex_json.save_file(build_projects_path, build_projects)

def _update_build_projects(project : str, config : str, compiler : str, createdProgram : str):
  """Update the build projects file and update the paths to new build projects"""
  build_projects = regis.rex_json.load_file(build_projects_path)

  project = project.lower()
  config = config.lower()
  compiler = compiler.lower()

  if project not in build_projects:
    build_projects[project] = {}
  
  build_project = build_projects[project]
  if config not in build_project:
    build_project[config] = {}
    
  build_config = build_project[config]
  if compiler not in build_config:
    build_config[compiler] = []

  build_projects[project][config][compiler].append(createdProgram)

  regis.rex_json.save_file(build_projects_path, build_projects)

def new_build(projectName : str, config : str, compiler : str, shouldBuild : bool = False, shouldClean : bool = False, slnFile : str = "", buildDependencies : bool = False, verboseOutput : bool = False):
  """This is the interface to the build pipeline.\n
  It'll launch a new build for the project using the config and compiler specified.\n
  It's possible to to negate building and only clean or to do a clean step before the build starts.\n
  It's also possible to only build the project and not its dependencies"""  
  slnFile = _look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("unable to find solution, aborting..")
    return 1
  
  project = _find_ninja_project_file(slnFile, projectName)
  with regis.dir_watcher.DirWatcher(intermediate_path, bRecursive=True) as dir_watcher:
    res = _launch_new_build(project, config, compiler, shouldBuild, shouldClean, buildDependencies, verboseOutput)

  if not os.path.exists(build_projects_path):
    regis.rex_json.save_file(build_projects_path, {})

  # it's possible nothing gets done because everything is up to date
  # in that case, we don't need to update anything
  for op in dir_watcher.operations:
    if regis.util.is_executable(op.filepath):
      if (op.op == regis.dir_watcher.FileOperation.Deleted):
        _update_cleaned_projects(projectName, config, compiler, op.filepath)
      elif (op.op == regis.dir_watcher.FileOperation.Created):
        _update_build_projects(projectName, config, compiler, op.filepath)

  return res
  
def build_all_configs(projectName : str, shouldBuild : bool = False, shouldClean : bool = False, slnFile : str = "", buildDependencies : bool = False, singleThreaded : bool = True, verboseOutput : bool = False):
  slnFile = _look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("unable to find solution, aborting..")
    return 1
  
  project = _find_ninja_project_file(slnFile, projectName)
  compilers = project.compilers()

  # This is the list that'll store the results of each build
  result_arr = []
  def _build_on_thread(prj, cfg, comp, result):
    result.append(_launch_new_build(prj, cfg, comp, shouldBuild, shouldClean, buildDependencies, verboseOutput))

  threads : list[threading.Thread] = []
  
  # loop over the configs and compilers and create a build for each combination
  for compiler in compilers:
    for config in compilers[compiler]:
      thread = threading.Thread(target=_build_on_thread, args=(project, config, compiler, result_arr))
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

  return result_arr.count(0) != len(result_arr)