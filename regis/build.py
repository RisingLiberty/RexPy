import os
import subprocess
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict

def __launch_new_build(sln_file : str, project : str, config : str, compiler : str, shouldClean : bool, alreadyBuild : list[str], intermediateDir : str = ""):
  sln_jsob_blob = CaseInsensitiveDict(regis.rex_json.load_file(sln_file))
  
  if project not in sln_jsob_blob:
    regis.diagnostics.log_err(f"project '{project}' was not found in solution, have you generated it?")
    return 1, alreadyBuild
  
  project_file_path = sln_jsob_blob[project]    
  json_blob = regis.rex_json.load_file(project_file_path)

  project_lower = project.lower()
  compiler_lower = compiler.lower()
  config_lower = config.lower()
  
  if compiler not in json_blob[project_lower]:
    regis.diagnostics.log_err(f"no compiler '{compiler}' found for project '{project}'")
    return 1, alreadyBuild
  
  if config not in json_blob[project_lower][compiler_lower]:
    regis.diagnostics.log_err(f"error in {project_file_path}")
    regis.diagnostics.log_err(f"no config '{config}' found in project '{project}' for compiler '{compiler}'")
    return 1, alreadyBuild

  ninja_file = json_blob[project_lower][compiler_lower][config_lower]["ninja_file"]
  dependencies = json_blob[project_lower][compiler_lower][config_lower]["dependencies"]

  regis.diagnostics.log_info(f"Building: {project}")

  ninja_path = tool_paths_dict["ninja_path"]
  if shouldClean:
    proc = regis.subproc.run(f"{ninja_path} -f {ninja_file} -t clean")
    proc.wait()

  proc = regis.subproc.run(f"{ninja_path} -f {ninja_file}")
  proc.wait()
  return proc.returncode, alreadyBuild

def new_build(sln_file : str, project : str, config : str, compiler : str, intermediateDir : str = "", shouldClean : bool = False):
  if not os.path.exists(sln_file):
    regis.diagnostics.log_err(f'solution path {sln_file} does not exist')
    return 1
  
  already_build = []
  res, build_projects = __launch_new_build(sln_file, project, config, compiler, shouldClean, already_build, intermediateDir)
  return res
  