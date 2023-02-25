import os
import rexpy.required_tools
import rexpy.rex_json
import rexpy.util

tool_paths_dict = rexpy.required_tools.tool_paths_dict

def new_build(project, config, compiler, shouldClean):
  root = rexpy.util.find_root()
  settings = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
  intermediate_folder = settings["intermediate_folder"]
  build_folder = settings["build_folder"]
  ninja_filename = f"{project}.{config}.{compiler}.ninja"
  ninja_filepath = os.path.join(root, intermediate_folder, build_folder, "ninja", project, "ninja", ninja_filename)

  ninja_path = tool_paths_dict["ninja_path"]
  if shouldClean:
    os.system(f"{ninja_path} -f {ninja_filepath} -t clean")

  return os.system(f"{ninja_path} -f {ninja_filepath}")