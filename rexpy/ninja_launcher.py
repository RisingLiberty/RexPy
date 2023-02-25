import argparse
import subprocess
import os
import psutil
import filelock
import sys
import rexpy.util
import rexpy.rex_json
import rexpy.diagnostics

def builds_in_flight_filepath():
  root = rexpy.util.find_root()
  settings = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "settings.json"))
  intermediate_folder = settings["intermediate_folder"]
  build_folder = settings["build_folder"]

  return os.path.join(root, intermediate_folder, build_folder, "ninja", "builds_in_flight.tmp")

def pid_for_build_in_flight(build_in_flight_file, ninja_file):
  lines : list[str] = build_in_flight_file.readlines()
  pid = -1
  for line in lines:
    if ninja_file in line:
      words = line.split(',')
      pid = words[1]

  return pid
  
def default_output_callback(pid, output):
  for line in iter(output.readline, b''):
    new_line : str = line.decode('UTF-8')

    if new_line.endswith('\n'):
      new_line = new_line.removesuffix('\n')

    rexpy.diagnostics.log_no_color(f"[pid:{pid}] {new_line}")    

def launch_new_build(ninja_exe, ninja_file, ninja_build, builds_in_flight_filepath):
    if ninja_build == None:
      raise Exception("Invalid build target")
  
    cmd = f"{ninja_exe} -f {ninja_file} {ninja_build}"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    rexpy.diagnostics.log_debug(f"[Ninja Launcher] Launching: {ninja_file} - {ninja_build} - pid: {proc.pid}")
    default_output_callback(proc.pid, proc.stdout)
    lock = filelock.FileLock(f"{builds_in_flight_filepath}.lock")
    with open(builds_in_flight_filepath, "a") as f:
      f.write(f"{ninja_file},{proc.pid}\n")
      lock.release()
    proc.wait()

    return proc.returncode

def wait_for_proc(pid):
  try:
    proc = psutil.Process(pid)
    proc.wait()
  except Exception as Ex:
    print(f"build with pid({pid}) was already closed")
  return

def remove_build_from_file(ninja_file, builds_in_flight_file_path):
  lines = []
  lock = filelock.FileLock(f"{builds_in_flight_file_path}.lock")
  with open(builds_in_flight_file_path, "r") as fp:
    lines = fp.readlines()

  with open(builds_in_flight_file_path, "w") as fp:
    for line in lines:
        if ninja_file not in line:
            fp.write(line)
  lock.release()

def run(ninja_exe : str, ninja_file : str, ninja_build : str):
  pid = -1
  if os.path.exists(builds_in_flight_filepath()):
    lock = filelock.FileLock(f"{builds_in_flight_filepath()}.lock")
    with open(builds_in_flight_filepath(), "r") as f:
      pid = int(pid_for_build_in_flight(f, ninja_file))
  
  return_code = 0
  if pid == -1:
    # no build in flight, launch a new one
    return_code = launch_new_build(ninja_exe, ninja_file, ninja_build, builds_in_flight_filepath())
    remove_build_from_file(ninja_file, builds_in_flight_filepath())
  else:
    # build in flight, wait for it to finish before starting a new one
    print(f"Waiting for build of file {ninja_file} to finish (PID: {pid})")
    wait_for_proc(pid)
    remove_build_from_file(ninja_file, builds_in_flight_filepath())

    # if there are no changes the following will exit quickly with "ninja: no work to do"
    return_code = launch_new_build(ninja_exe, ninja_file, ninja_build, builds_in_flight_filepath())
    remove_build_from_file(ninja_file, builds_in_flight_filepath())

  return return_code

if __name__ == "__main__":
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)

  parser.add_argument("-exe", help="path to ninja exe")
  parser.add_argument("-file", help="path to ninja file")
  parser.add_argument("-build", help="build name to execute")
  
  args, unknown = parser.parse_known_args()

  ninja_exe = args.exe
  ninja_file = args.file
  ninja_build = args.build

  res = run(ninja_exe, ninja_file, ninja_build)
  sys.exit(res)

