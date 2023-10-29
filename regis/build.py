import os
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc

from pathlib import Path

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict
already_build : list[str] = []

class NinjaProject:
  def __init__(self, filepath):
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

    regis.diagnostics.log_info(f"Building: {self.project_name}")

    # then build the project we specified
    ninja_path = tool_paths_dict["ninja_path"]
    proc = regis.subproc.run(f"{ninja_path} -f {self.ninja_file(compiler, config, buildDependencies)}")
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

      # Don't build it if we're already build it
      if dependency_project_name in already_build:
        continue
      
      dependency_project = NinjaProject(dependency)
      r |= dependency_project.build(compiler, config, buildDependencies=True)

      already_build.append(dependency_project_name)

    return r

def find_sln(directory):
  dirs = os.listdir(directory)

  res = []

  for dir in dirs:
    full_path = os.path.join(directory, dir)
    if os.path.isfile(full_path) and Path(full_path).suffix == ".nsln":
      res.append(full_path)
    
  return res

def __launch_new_build(sln_file : str, projectName : str, config : str, compiler : str, shouldBuild : bool, shouldClean : bool, buildDependencies = False):
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

def __look_for_sln_file_to_use(slnFile : str):
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

def new_build(project : str, config : str, compiler : str, shouldBuild : bool = False, shouldClean : bool = False, slnFile : str = "", buildDependencies : bool = False):
  slnFile = __look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("unable to find solution, aborting..")
    return 1
  
  res = __launch_new_build(slnFile, project, config, compiler, shouldBuild, shouldClean, buildDependencies)
  return res
  