import os
import regis.required_tools
import regis.rex_json
import regis.util
import regis.diagnostics
import regis.subproc

from pathlib import Path

from requests.structures import CaseInsensitiveDict

tool_paths_dict = regis.required_tools.tool_paths_dict

def find_sln_in_cwd():
  dirs = os.listdir()

  res = []

  for dir in dirs:
    if os.path.isfile(dir) and Path(dir).suffix == ".nsln":
      res.append(dir)
    
  return res

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

def __look_for_sln_file_to_use(slnFile : str):
  if slnFile == "":
    sln_files = find_sln_in_cwd()

    if len(sln_files) > 1:
      regis.diagnostics.log_err(f'more than 1 nsln file was found in the cwd, please specify which one you want to use')
    
      for file in sln_files:
        regis.diagnostics.log_err(f'-{file}')
    
      return ""
    
    if len(sln_files) == 0:
      regis.diagnostics.log_err(f'no nlsn found in {os.getcwd()}')
      return ""

    slnFile = sln_files[0]
  elif not os.path.exists(slnFile):
    regis.diagnostics.log_err(f'solution path {slnFile} does not exist')
    return ""
  
  return slnFile

def new_build(project : str, config : str, compiler : str, intermediateDir : str = "", shouldClean : bool = False, slnFile : str = ""):
  slnFile = __look_for_sln_file_to_use(slnFile)

  if slnFile == "":
    regis.diagnostics.log_err("aborting..")
    return 1
  
  already_build = []
  res, build_projects = __launch_new_build(slnFile, project, config, compiler, shouldClean, already_build, intermediateDir)
  return res
  