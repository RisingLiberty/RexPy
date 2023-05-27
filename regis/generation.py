import os
import regis.diagnostics
import regis.rex_json
import regis.util
import regis.required_tools
import regis.subproc
import regis.diagnostics

from pathlib import Path

root = regis.util.find_root()
settings = regis.rex_json.load_file(os.path.join(root, regis.util.settingsPathFromRoot))
temp_dir = os.path.join(root, settings["intermediate_folder"])
tools_install_dir = os.path.join(temp_dir, settings["tools_folder"])
tool_paths_filepath = os.path.join(tools_install_dir, "tool_paths.json")
tool_paths_dict = regis.rex_json.load_file(tool_paths_filepath)

def __find_sharpmake_files(directory):
  sharpmakes_files = []
  for root, dirs, files in os.walk(directory):
    for file in files:
      extensions = Path(file).suffixes
      if len(extensions) == 2:
        if extensions[0] == ".sharpmake" and extensions[1] == ".cs":
          path = os.path.join(root, file)
          sharpmakes_files.append(path)
  
  return sharpmakes_files

def __find_sharpmake_root_files(directory):
  sharpmakes_files = []
  for root, dirs, files in os.walk(directory):
    for file in files:
      extensions = Path(file).suffixes
      if len(extensions) == 1:
        if extensions[0] == ".cs":
          path = os.path.join(root, file)
          sharpmakes_files.append(path)

  return sharpmakes_files

def __scan_for_sharpmake_files(settingsPath : str):
  """
  scans for sharpmake files in the current directory using the settings.
  it searches for all the sharpmake files in the sharpmake root, source folder and test folder.
  all searches are done recursively.
  """
  settings = regis.rex_json.load_file(settingsPath)
  sharpmake_root = os.path.join(root, "_build", "sharpmake")
  source_root = os.path.join(root, settings["source_folder"])
  tests_root = os.path.join(root, settings["tests_folder"])
  
  sharpmakes_files = []
  sharpmakes_files.extend(__find_sharpmake_root_files(sharpmake_root))
  sharpmakes_files.extend(__find_sharpmake_files(source_root))
  sharpmakes_files.extend(__find_sharpmake_files(tests_root))

  return sharpmakes_files

def new_generation(settingsPath : str, sharpmakeArgs : str = ""):
  """
  performs a new generation using the sharpmake files found by searching the current directory recursively.
  '/diagnostics' is always added as a sharpmake arguments.
  """

  sharpmake_files = __scan_for_sharpmake_files(settingsPath)
  
  sharpmake_path = tool_paths_dict["sharpmake_path"]
  if len(sharpmake_path) == 0:
    regis.diagnostics.log_err("Failed to find sharpmake path")
    return

  sharpmake_sources = ""
  for sharpmake_file in sharpmake_files:
    sharpmake_sources += "\""
    sharpmake_sources += sharpmake_file
    sharpmake_sources += "\", "

  sharpmake_sources = sharpmake_sources[0:len(sharpmake_sources) - 2]
  sharpmake_sources = sharpmake_sources.replace('\\', '/')

  return regis.subproc.run(f"{sharpmake_path} /sources({sharpmake_sources}) /diagnostics {sharpmakeArgs}")
