import os
import shutil
import rexpy.util

def __install(hooksPath):
    root_path = rexpy.util.find_root()
    hooks = os.listdir(hooksPath)

    for hook in hooks:
        src = os.path.join(hooksPath, hook)
        dst = os.path.join(root_path, ".git", "hooks", hook)
        shutil.copy(src, dst)

def run(hooksPath):
    __install(hooksPath)