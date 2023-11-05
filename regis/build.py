import os
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc
import regis.dir_watcher

from pathlib import Path

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict
root = regis.util.find_root()  
settings_path = os.path.join(root, regis.util.settingsPathFromRoot)
settings = regis.rex_json.load_file(settings_path)
intermediate_path = os.path.join(root, settings['intermediate_folder'], settings['build_folder'])
build_projects_path = os.path.join(intermediate_path, settings['build_projects_filename'])

class NinjaProject:
  def _init_(self, filepath):
    self.json_blob : dict = regis.rex_json.load_file(filepath)
    self.filepath = filepath
    self.project_name = list(self.json_blob.keys())[0].lower() # the project name is the root key

  def ninja_file(self, compiler : str, config : str, buildDependencies : bool):
    if buildDependencies:
      return self.json_blob[self.project_name][compiler.lower()][config.lower()]["ninja_file"]
    else:
      return self.json_blob[self.project_name][compiler.lower()][config.lower()]["ninja_file_no_deps"]

  def dependencies(self, compiler : str, config : str):
    return self.json_blob[self.project_name.lower()][compiler.lower()][config.lower()]["dependencies"]

  def clean(self, compiler : str, config : str, buildDependencies : bool):
    ninja_path = tool_paths_dict["ninja_path"]
    regis.diagnostics.log_info(f'Cleaning intermediates')
    
    r = self._valid_args_check(compiler, config)
    if r != 0:
      return r

    proc = regis.subproc.run(f"{ninja_path} -f {self.ninja_file(compiler, config, buildDependencies)} -t clean")
    proc.wait()

    r = proc.returncode
    return r
  
  def build(self, compiler : str, config : str, buildDependencies : bool):
    r = 0

    r = self._valid_args_check(compiler, config)
    if r != 0:
      return r

    # make sure to build the dependencies first
    if buildDependencies:
      r |= self._build_dependencies(compiler, config)

    regis.diagnostics.log_info(f"Building: {self.project_name} - {config} - {compiler}")

    # then build the project we specified
    ninja_path = tool_paths_dict["ninja_path"]
    cmd = f"{ninja_path} -f {self.ninja_file(compiler, config, buildDependencies)}"
    regis.diagnostics.log_info(f'executing: {cmd}')
    proc = regis.subproc.run(cmd)
    proc.wait()
    r = proc.returncode

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
    if compiler not in self.json_blob[self.project_name]:
      regis.diagnostics.log_err(f"no compiler '{compiler}' found for project '{self.project_name}'")
      return 1
  
    if config not in self.json_blob[self.project_name][compiler]:
      regis.diagnostics.log_err(f"error in {self.filepath}")
      regis.diagnostics.log_err(f"no config '{config}' found in project '{self.project_name}' for compiler '{compiler}'")
      return 1
    
    return 0

  def _build_dependencies(self, compiler, config):
    dependencies = self.json_blob[self.project_name][compiler][config]["dependencies"]

    r = 0
    for dependency in dependencies:      
      dependency_project_name = Path(dependency).stem
      regis.diagnostics.log_info(f'Building dependency: {self.project_name} -> {dependency_project_name}')

      dependency_project = NinjaProject(dependency)
      r |= dependency_project.build(compiler, config, buildDependencies=True)

    return r

def find_sln(directory):
  """Find the ninja solution in the specified directory"""
  dirs = os.listdir(directory)

  res = []

  for dir in dirs:
    full_path = os.path.join(directory, dir)
    if os.path.isfile(full_path) and Path(full_path).suffix == ".nsln":
      res.append(full_path)
    
  return res

def _launch_new_build(sln_file : str, projectName : str, config : str, compiler : str, shouldBuild : bool, shouldClean : bool, buildDependencies = False):
  """Load the solution, look for the project in the solution and build it"""
  sln_jsob_blob = CaseInsensitiveDict(regis.rex_json.load_file(sln_file))
  
  if projectName not in sln_jsob_blob:
    regis.diagnostics.log_err(f"project '{projectName}' was not found in solution, have you generated it?")
    return 1
  
  project_file_path = sln_jsob_blob[projectName]    
  project = NinjaProject(project_file_path)

  compiler_lower = compiler.lower()
  config_lower = config.lower()

  r = 0

  if shouldClean:
    r |= project.clean(compiler_lower, config_lower, buildDependencies)

  if shouldBuild:
    r |= project.build(compiler_lower, config_lower, buildDependencies)

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

def _update_cleaned_projects(project : str, config : str, compiler : str, deletedPrograms : list[str]):
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

  for deleted_program in deletedPrograms:
    if deleted_program in build_programs:
      build_programs.remove(deleted_program)

  regis.rex_json.save_file(build_projects_path, build_projects)

def _update_build_projects(project : str, config : str, compiler : str, paths : list[str]):
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
    
  build_projects[project][config][compiler] = paths

  regis.rex_json.save_file(build_projects_path, build_projects)

def new_build(project : str, config : str, compiler : str, shouldBuild : bool = False, shouldClean : bool = False, slnFile : str = "", buildDependencies : bool = False):
  """This is the interface to the build pipeline.\n
  It'll launch a new build for the project using the config and compiler specified.\n
  It's possible to to negate building and only clean or to do a clean step before the build starts.\n
  It's also possible to only build the project and not its dependencies"""
  slnFile = _look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("unable to find solution, aborting..")
    return 1
  
  with regis.dir_watcher.DirWatcher(intermediate_path, bRecursive=True) as dir_watcher:
    res = _launch_new_build(slnFile, project, config, compiler, shouldBuild, shouldClean, buildDependencies)

  programs_deleted = dir_watcher.filter_deleted_files(lambda path: path.endswith('.exe'))
  programs_created = dir_watcher.filter_created_or_modified_files(lambda path: path.endswith('.exe'))

  if not os.path.exists(build_projects_path):
    regis.rex_json.save_file(build_projects_path, {})

  # it's possible nothing gets done because everything is up to date
  # in that case, we don't need to update anything
  if len(programs_deleted) != 0 and len(programs_created) != 0:
    _update_cleaned_projects(args.project, args.config, args.compiler, programs_deleted)
    _update_build_projects(args.project, args.config, args.compiler, programs_created)

  return res
  