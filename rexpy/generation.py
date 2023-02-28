import os
import rexpy.diagnostics
import rexpy.rex_json
import rexpy.util
import rexpy.required_tools
import rexpy.subproc
import rexpy.diagnostics

root = rexpy.util.find_root()
settings = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
temp_dir = os.path.join(root, settings["intermediate_folder"])
tools_install_dir = os.path.join(temp_dir, settings["tools_folder"])
tool_paths_filepath = os.path.join(tools_install_dir, "tool_paths.json")
tool_paths_dict = rexpy.rex_json.load_file(tool_paths_filepath)

def new_generation(sharpmakeFiles : list[str], sharpmakeArgs : list[str]):
  sharpmake_path = tool_paths_dict["sharpmake_path"]
  if len(sharpmake_path) == 0:
    rexpy.diagnostics.log_err("Failed to find sharpmake path")
    return

  sharpmake_sources = ""
  for sharpmake_file in sharpmakeFiles:
    sharpmake_sources += "\""
    sharpmake_sources += sharpmake_file
    sharpmake_sources += "\", "

  sharpmake_sources = sharpmake_sources[0:len(sharpmake_sources) - 2]
  sharpmake_sources = sharpmake_sources.replace('\\', '/')

  rexpy.subproc.run(f"{sharpmake_path} /sources({sharpmake_sources}) /diagnostics {sharpmakeArgs}")
