import os
import json
import requests
import zipfile
import shutil
from enum import Enum

import rexpy.diagnostics
import rexpy.util
import rexpy.rex_json

class Host(Enum):
    UNKNOWN = 0
    GITLAB = 1
    GITHUB = 2

def __get_script_path():
    return os.path.dirname(os.path.realpath(__file__))

def __get_host(path):
    if "gitlab" in path:
        return Host.GITLAB
    elif "github" in path:
        return Host.GITHUB
    
    rexpy.diagnostics.log_info("Unknown host!")
    return Host.UNKNOWN

def __build_gitlab_path(baseUrl, name, tag):
    url = os.path.join(baseUrl, "-")
    url = os.path.join(url, "archive")
    url = os.path.join(url, tag)
    url = os.path.join(url, name+"-"+tag+".zip")
    url = url.replace("\\", "/")
    return url
def __build_github_path(baseUrl, tag):
    url = os.path.join(baseUrl, "archive")
    url = os.path.join(url, "refs")
    url = os.path.join(url, "tags")
    url = os.path.join(url, tag+".zip")
    url = url.replace("\\", "/")
    return url
def __build_host_path(baseUrl, name, tag):
    host = __get_host(baseUrl)
    if host == Host.GITHUB:
        return __build_github_path(baseUrl, tag)
    elif host == Host.GITLAB:
        return __build_gitlab_path(baseUrl, name, tag)
    else:
        rexpy.diagnostics.log_err(f"Unknown url host: {host} in url: {baseUrl}")
        return ""

def __load_externals_required():
    root = rexpy.util.find_root()

    json_blob = rexpy.rex_json.load_file(os.path.join(root, "build", "config", "required_externals.json"))
    if json_blob == None:
        rexpy.diagnostics.log_err("Loaded json blob is None, stopping json parse")
        return []

    externals_required = []
    for object in json_blob:
        externals_required.append(json_blob[object])

    return externals_required

def __download_external(url):
    # get basename of the URL (a.k.a. the filename + extention we would like to download)
    url_basename = os.path.basename(url)

    # request a download of the given URL
    if not os.path.exists(url_basename):
        response = requests.get(url)
        if response.status_code == requests.codes.ok:
            # write the downloaded file to disk
            open(url_basename, "wb").write(response.content)
        else:
            # bad request was made
            rexpy.diagnostics.log_err(f"Bad request [{str(response.status_code)}] for given url: {url}")
            return 1
        
    # extract the zip file on disk
    # we cache the files within the directory before 
    # and after extraction, this gives us the ability
    # to examine the added files within the directory
    rexpy.diagnostics.log_info("Extracting: " + url)
    
    # pre list directories
    # cached directories before we downloaded anything
    pre_list_dir = os.listdir(__get_script_path())
    with zipfile.ZipFile(url_basename,"r") as zip_ref:
        zip_ref.extractall(__get_script_path())

    # post list directories
    # directories after we downloaded the repository
    post_list_dir = os.listdir(__get_script_path())

    rexpy.diagnostics.log_info("Looking for added extracted directories ...")
    added_directory_names = []
    for post_dir in post_list_dir:
        count = pre_list_dir.count(post_dir)
        if count == 0:
            added_directory_names.append(post_dir)
    rexpy.diagnostics.log_info(f"Found ({str(len(added_directory_names))}): ".join(added_directory_names))

    # remove the created zip file
    os.remove(url_basename)

    return added_directory_names

def __create_version_file(externalsDir, tag):
    version = {
        "tag": tag
    }

    json_object = json.dumps(version, indent=4)

    # Writing to version.json
    with open(os.path.join(externalsDir, "version.json"), "w") as out:
        out.write(json_object)

def __verify_external(externalPath, requiredTag):
    external_name = os.path.basename(externalPath)

    if os.path.exists(externalPath):
        rexpy.diagnostics.log_no_color(f"External found: {external_name}")
        rexpy.diagnostics.log_no_color(f"validating version ...")
        version_file = os.path.join(externalPath, "version.json")
        if os.path.exists(version_file):
            version_data = rexpy.rex_json.load_file(version_file)           
            if version_data == None:
                rexpy.diagnostics.log_err(f"Invalid version data found, redownloading external: {external_name}")
                return False             
            if not version_data["tag"] == requiredTag:
                return False
            else:
                rexpy.diagnostics.log_no_color(f"External: {external_name} is up to date ({external_name} {requiredTag})")
                return True
        else:
            rexpy.diagnostics.log_err(f"No version file found for {external_name}")
            return False

    else:
        return False

def __install_external(external):
    root = rexpy.util.find_root()

    external_url = external["url"]
    external_name = external["name"]
    external_tag = external["tag"]
    external_store = external["storage"]
    external_store = external_store.replace("~", root)

    externals_dir = os.path.join(external_store, external_name)

    # if the external is already present we need to check if we need to redownload anything
    valid_external = __verify_external(externals_dir, external_tag)
    if not valid_external:    
        # any data that was already available will be deleted 
        # the data will be out of date anyway when a download is triggered
        if os.path.exists(externals_dir):
            shutil.rmtree(externals_dir)

        url = __build_host_path(external_url, external_name, external_tag)
        added_directories = __download_external(url)     

        if len(added_directories) == 1:
            # move to output directory
            shutil.move(os.path.join(__get_script_path(), added_directories[0]), os.path.join(external_store, added_directories[0]))
            # change directory name
            cwd = os.getcwd()
            os.chdir(external_store)
            os.rename(added_directories[0], external_name)
            os.chdir(cwd)
        elif len(added_directories) > 1:
            # create output directory
            if not os.path.exists(externals_dir):
                os.makedirs(externals_dir)
            # move to output directory
            for added_directory in added_directories:
                shutil.move(os.path.join(__get_script_path(), added_directory), externals_dir)
        else:
            rexpy.diagnostics.log_err("No directories where extracted.")
            return

        __create_version_file(externals_dir, external_tag)   

def run():
    rexpy.diagnostics.log_info("Start installing externals ...")

    externals_required = __load_externals_required()
    if externals_required == None:
        rexpy.diagnostics.log_err("Required externals is None, exiting ...")
        return

    for external in externals_required:
        __install_external(external)    
