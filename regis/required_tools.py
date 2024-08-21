import os
import sys
import regis.rex_json
import regis.util
import regis.task_raii_printing
import regis.diagnostics
import regis.vs
import requests
import zipfile 
import shutil
import threading
import argparse

from pathlib import Path

root = regis.util.find_root()
settings = regis.rex_json.load_file(os.path.join(root, regis.util.settingsPathFromRoot))
build_dir = os.path.join(root, settings["build_folder"])
temp_dir = os.path.join(root, settings["intermediate_folder"])
tools_install_dir = os.path.join(temp_dir, settings["tools_folder"])
tool_paths_filepath = os.path.join(tools_install_dir, "tool_paths.json")
zip_downloads_path = os.path.join(tools_install_dir, "zips")

tool_paths_dict = {}
if os.path.exists(tool_paths_filepath):
  tool_paths_dict = regis.rex_json.load_file(tool_paths_filepath)
required_tools = []
not_found_tools = []
found_tools = []

def __load_required_tools_dict():
  tools_required = []
  json_blob = regis.rex_json.load_file(os.path.join(root, "_build", "config", "required_tools.json"))
  for object in json_blob:
    tools_required.append(json_blob[object])

  return tools_required

def __print_tool_found(tool, path : str):
  regis.diagnostics.log_no_color(f"{tool['config_name']} found at {path}")

def __get_tool_extension(tool):
  extension = "" 
  if "extension" in tool:
    extension = tool["extension"]
  elif regis.util.is_windows():
    extension = ".exe"

  return extension

def __get_msvc_paths(msvcRelPath : str):
  res = []

  installed_vs_versions = regis.vs.installed_versions()
  tool_path = msvcRelPath
  for installed_vs in installed_vs_versions:
    msvc_path = os.path.join(installed_vs.installation_path, 'VC', 'Tools', tool_path)
    if os.path.exists(msvc_path):
      res.append(msvc_path)
    
  return res

def __get_possible_tool_install_dirs(requiredTool : dict):
  res = []

  # we purposely don't look in the PATH env variable
  # as we cannot confidently check version of tools
  # found in PATH.

  # some tools have specific locations they can be installed at
  if requiredTool['archive_name'] == 'MSVC':
    res.extend(__get_msvc_paths(requiredTool['path']))

  return res

def __look_for_tool_on_system(requiredTool):
    possible_paths = __get_possible_tool_install_dirs(requiredTool)

    # look for the tool
    exe_extension = __get_tool_extension(requiredTool)
    tool_path = regis.util.find_file_in_paths(f"{requiredTool['stem']}{exe_extension}", possible_paths)

    return tool_path

def __look_for_tools(required_tools):   
  for required_tool in required_tools:
    stem = required_tool["stem"]
    path = os.path.join(tools_install_dir, required_tool["archive_name"])
    version = regis.util.load_version_file(path)

    # If the version file is not found
    # we look for the tool somewhere else on the system
    if not version:
      tool_path = __look_for_tool_on_system(required_tool)
      # if the tool is found, we save this path instead
      # we don't download the tool from the web
      if tool_path != '':
        __print_tool_found(required_tool, tool_path)
        tool_config_name = required_tool["config_name"]
        tool_paths_dict[tool_config_name] = tool_path
        found_tools.append(required_tool)
        continue

      regis.diagnostics.log_err(f"{stem} not found")
      not_found_tools.append(required_tool)
      continue

    # check if our version is up to date
    if version != required_tool["version"]:
      regis.diagnostics.log_err(f"{stem} is out of date")
      not_found_tools.append(required_tool)
      continue

    config_name = required_tool["config_name"]

    # check if the tool path is already in the cached paths
    if config_name in tool_paths_dict:
      tool_path = tool_paths_dict[config_name]
      if (os.path.exists(tool_path)):
          regis.diagnostics.log_no_color(f"{stem} found at {tool_path}")
          continue
      else:
        regis.diagnostics.log_err(f"Error: tool path cached, but path doesn't exist: {tool_path}")
        not_found_tools.append(required_tool)
        continue

    # if not, add the path of the tool directory where it'd be downloaded to
    paths_to_use = []
    paths_to_use.append(os.path.join(tools_install_dir, required_tool["path"]))

    # look for the tool
    exe_extension = __get_tool_extension(required_tool)
    tool_path = regis.util.find_file_in_paths(f"{stem}{exe_extension}", paths_to_use)

    # tool is found, add it to the cached paths
    if tool_path != '':
      __print_tool_found(required_tool, tool_path)
      tool_config_name = required_tool["config_name"]
      tool_paths_dict[tool_config_name] = tool_path
      found_tools.append(required_tool)
    # tool is not found, add it to the list to be looked for later
    else:
      not_found_tools.append(required_tool)

  return not_found_tools

def _are_installed():
  with regis.task_raii_printing.TaskRaiiPrint("Checking if tools are installed"):

    global required_tools
    required_tools = __load_required_tools_dict()
    
    global tool_paths_dict
    if tool_paths_dict == None:
      tool_paths_dict = {}
      
    global not_found_tools
    not_found_tools = __look_for_tools(required_tools)

    if len(not_found_tools) == 0:
      regis.diagnostics.log_info("All tools found")
      regis.rex_json.save_file(tool_paths_filepath, tool_paths_dict)
      return True
    else:
      regis.diagnostics.log_warn(f"Tools that weren't found or were out of date: ")
      for tool in not_found_tools:
        regis.diagnostics.log_warn(f"\t-{tool['stem']}")

  return False

def __download_file(url):
  filename = os.path.basename(url)
  filePath = os.path.join(zip_downloads_path, filename)
  
  if not os.path.exists(filePath):
    response = requests.get(url)
    open(filePath, "wb").write(response.content)
  
def __make_zip_download_path():
  if not os.path.exists(zip_downloads_path):
    os.makedirs(zip_downloads_path)

def __download_tool(name, version, numZipFiles):
  with regis.task_raii_printing.TaskRaiiPrint(f"Downloading tool {name} {version}"):

    with regis.util.LoadingAnimation('Downloading'):

      threads = []
      for i in range(numZipFiles):
        threads.append(__launch_download_thread((f"https://github.com/RisingLiberty/RegisZip/raw/{version}/data/{name}.zip.{(i + 1):03d}")))

      for thread in threads:
        thread.join()

def __download_tools_archive():
  with regis.task_raii_printing.TaskRaiiPrint("Downloading tools"):

    # filter duplicate tools
    tools_to_download = []
    for not_found_tool in not_found_tools:
      archive_name = not_found_tool["archive_name"]
      should_add = True
      for tool_to_download in tools_to_download:
        if archive_name == tool_to_download["archive_name"]:
          should_add = False
          break
      
      if should_add:
        tools_to_download.append(not_found_tool)

    for not_found_tool in tools_to_download:
      arch_name = not_found_tool["archive_name"]
      num_zip_files = not_found_tool["num_zip_files"]
      version = not_found_tool["version"]
      __download_tool(arch_name, version, num_zip_files)

    return tools_to_download
    
def __enumerate_tools(zipsFolder):
  zips = os.listdir(zipsFolder)
  tools = []
  for zip in zips:
    stem = Path(zip).stem
    if stem not in tools:
      tools.append(stem)

  return tools

def __zip_files_for_tool(stem, folder):
  zips = os.listdir(folder)
  tool_zip_files = []
  for zip in zips:
    if Path(zip).stem == stem:
      tool_zip_files.append(os.path.join(folder, zip))

  return tool_zip_files

def __unzip_tools():
  with regis.task_raii_printing.TaskRaiiPrint("Unzipping files"):
    tools_to_unzip = __enumerate_tools(zip_downloads_path)

    with regis.util.LoadingAnimation('Extracting zips'):
      for tool in tools_to_unzip:
        tool_zip_files = __zip_files_for_tool(tool, zip_downloads_path)
        tool_master_zip = os.path.join(zip_downloads_path, f"{tool}")
        regis.diagnostics.log_info(f'extracting {tool} to {tool_master_zip}')
        with open(tool_master_zip, "ab") as f:
          for tool_zip in tool_zip_files:
            with open(tool_zip, "rb") as z:
                f.write(z.read())

        try:
          with zipfile.ZipFile(tool_master_zip, "r") as zip_obj:
              zip_obj.extractall(tools_install_dir)
        except zipfile.BadZipFile as ex:
          regis.diagnostics.log_err(f'Unable to extract {tool_master_zip}. {ex}')
          sys.exit(1)

      regis.diagnostics.log_info(f"tools unzipped to {tools_install_dir}")

def __create_version_files(foundTools : []):
  for tool in foundTools:
    path = os.path.join(tools_install_dir, tool["archive_name"])
    regis.util.create_version_file(path, tool["version"])

def __delete_tmp_folders():
  if os.path.isdir(zip_downloads_path):
    shutil.rmtree(zip_downloads_path)

def __launch_download_thread(url):
    thread = threading.Thread(target=__download_file, args=(url,))
    thread.start()
    return thread  

def _download():
  with regis.task_raii_printing.TaskRaiiPrint("Downloading tools"):
    __delete_tmp_folders() # clean up if last job failed
    __make_zip_download_path()
    __download_tools_archive()
    __unzip_tools()
    __delete_tmp_folders()

def _install():
  with regis.task_raii_printing.TaskRaiiPrint("installing tools"):

    global tool_paths_dict
    global not_found_tools
    for tool in not_found_tools:

      # look for tool in the folder where it'd be downloaded to
      exe_extension = __get_tool_extension(tool)
      path = regis.util.find_file_in_folder(f"{tool['stem']}{exe_extension}", os.path.join(tools_install_dir, tool["path"]))

      # if not found, something is wrong and we have to investigate manually
      if path == "":
        tool_name = tool["stem"]
        regis.diagnostics.log_err(f"failed to find {tool_name}")
      else:
        # if found, add it to the cached paths
        __print_tool_found(tool, path)
        tool_config_name = tool["config_name"]
        tool_paths_dict[tool_config_name] = path
    
    found_tools.extend(not_found_tools)

    __create_version_files(found_tools)

    # save cached paths to disk
    regis.rex_json.save_file(tool_paths_filepath, tool_paths_dict)

def query():
  """Query which required tools are still missing on the current machine."""
  return _are_installed()

def install():
  if not _are_installed():
    _download()
    _install()

