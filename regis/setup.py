import os
import argparse
import regis.util
import regis.rex_json
import regis.required_tools
import regis.required_libs
import shutil

root_path = regis.util.find_root()
settings = regis.rex_json.load_file(os.path.join(root_path, "build", "config", "settings.json"))
intermediate_dir = os.path.join(regis.util.find_root(), settings["intermediate_folder"])

def __clean_intermediate():
  # this clean the entire intermediate directory and all sub folders
  if os.path.exists(intermediate_dir):
    shutil.rmtree(intermediate_dir)

def run(shouldClean):
  if shouldClean:
    __clean_intermediate()
      
  regis.required_tools.run(False)
  regis.required_libs.run()
      
if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("-clean", help="clean setup, as if run for the first time", action="store_true")
  args, unknown = parser.parse_known_args()

  run(args.clean)