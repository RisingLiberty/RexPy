import os
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc

from pathlib import Path

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict

def find_sln(directory):
  dirs = os.listdir(directory)

  res = []

  for dir in dirs:
    full_path = os.path.join(directory, dir)
    if os.path.isfile(full_path) and Path(full_path).suffix == ".nsln":
      res.append(full_path)
    
  return res

def __launch_new_build(sln_file : str, project : str, config : str, compiler : str, shouldClean : bool, alreadyBuild : list[str], intermediateDir : str = "", dontBuildDependencies = False):
  sln_jsob_blob = CaseInsensitiveDict(regis.rex_json.load_file(sln_file))
  
  if project not in sln_jsob_blob:
    regis.diagnostics.log_err(f"project '{project}' was not found in solution, have you generated it?")
    return 1, alreadyBuild
  
  project_file_path = sln_jsob_blob[project]    
  json_blob = regis.rex_json.load_file(project_file_path)

  project_lower = project.lower()
  compiler_lower = compiler.lower()
  config_lower = config.lower()
  
  if compiler_lower not in json_blob[project_lower]:
    regis.diagnostics.log_err(f"no compiler '{compiler_lower}' found for project '{project}'")
    return 1, alreadyBuild
  
  if config not in json_blob[project_lower][compiler_lower]:
    regis.diagnostics.log_err(f"error in {project_file_path}")
    regis.diagnostics.log_err(f"no config '{config}' found in project '{project}' for compiler '{compiler}'")
    return 1, alreadyBuild

  ninja_file = json_blob[project_lower][compiler_lower][config_lower]["ninja_file"]

  # first build the dependencies
  if not dontBuildDependencies:
    dependencies = json_blob[project_lower][compiler_lower][config_lower]["dependencies"]

    for dependency in dependencies:
      dependency_project_name = Path(dependency).stem

      if dependency_project_name in alreadyBuild:
        continue

      res, buildProjects = __launch_new_build(sln_file, dependency_project_name, config, compiler, shouldClean, alreadyBuild, intermediateDir, dontBuildDependencies)
      if res == 0:
        alreadyBuild.append(dependency_project_name)
      else:
        regis.diagnostics.log_err(f"Failed to build {dependency_project_name}")
        return res, alreadyBuild

  regis.diagnostics.log_info(f"Building: {project}")

  ninja_path = tool_paths_dict["ninja_path"]
  if shouldClean:
    regis.diagnostics.log_info(f'Cleaning intermediates')
    proc = regis.subproc.run(f"{ninja_path} -f {ninja_file} -t clean")
    proc.wait()

  proc = regis.subproc.run(f"{ninja_path} -f {ninja_file}")
  proc.wait()
  return proc.returncode, alreadyBuild

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

def new_build(project : str, config : str, compiler : str, intermediateDir : str = "", shouldClean : bool = False, slnFile : str = "", dontBuildDependencies : bool = False):
  slnFile = __look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("aborting..")
    return 1
  
  already_build = []
  res, build_projects = __launch_new_build(slnFile, project, config, compiler, shouldClean, already_build, intermediateDir, dontBuildDependencies)
  return res
  