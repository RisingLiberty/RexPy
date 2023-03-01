import os
import rexpy.diagnostics
import rexpy.rex_json
import rexpy.util
import rexpy.required_tools
import rexpy.subproc
import rexpy.diagnostics

from pathlib import Path

root = rexpy.util.find_root()
settings = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
temp_dir = os.path.join(root, settings["intermediate_folder"])
tools_install_dir = os.path.join(temp_dir, settings["tools_folder"])
tool_paths_filepath = os.path.join(tools_install_dir, "tool_paths.json")
tool_paths_dict = rexpy.rex_json.load_file(tool_paths_filepath)

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

def __load_sharpmake_files(sharpmakePath : str):
  settings = rexpy.rex_json.load_file(sharpmakePath)
  sharpmake_root = os.path.join(root, settings["build_folder"], "sharpmake")
  source_root = os.path.join(root, settings["source_folder"])
  tests_root = os.path.join(root, settings["tests_folder"])
  
  sharpmakes_files = []
  sharpmakes_files.extend(__find_sharpmake_root_files(sharpmake_root))
  sharpmakes_files.extend(__find_sharpmake_files(source_root))
  sharpmakes_files.extend(__find_sharpmake_files(tests_root))

  return sharpmakes_files

def new_generation(settingsPath : str, sharpmakeArgs : list[str]):
  sharpmake_files = __load_sharpmake_files(settingsPath)
  
  sharpmake_path = tool_paths_dict["sharpmake_path"]
  if len(sharpmake_path) == 0:
    rexpy.diagnostics.log_err("Failed to find sharpmake path")
    return

  sharpmake_sources = ""
  for sharpmake_file in sharpmake_files:
    sharpmake_sources += "\""
    sharpmake_sources += sharpmake_file
    sharpmake_sources += "\", "

  sharpmake_sources = sharpmake_sources[0:len(sharpmake_sources) - 2]
  sharpmake_sources = sharpmake_sources.replace('\\', '/')

  return rexpy.subproc.run(f"{sharpmake_path} /sources({sharpmake_sources}) /diagnostics {sharpmakeArgs}")
