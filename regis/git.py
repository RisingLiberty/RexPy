import os

import regis.util
import regis.rex_json

changes_cache_filepath = os.path.join(".git", "file_changed")

def __zsplit(s: str) -> list[str]:
  s = s.strip('\0')
  s = s.strip('\n')
  if s:
      return s.split('\n')
  else:
      return []
  
def get_staged_files():
  cmd = 'git diff --staged --name-only --no-ext-diff'
  output, errc = regis.util.run_and_get_output(cmd)
  return __zsplit(output)

def get_local_branchname():
  cmd = 'git rev-parse --abbrev-ref HEAD'
  output, errc = regis.util.run_and_get_output(cmd)
  return output.strip('\n')

def cache_commit_changes(branch : str, files : list[str]):
  changes_cache_filepath = os.path.join(regis.util.find_root(), changes_cache_filepath)

  cached_changes = {}
  if os.path.exists(changes_cache_filepath):
    cached_changes = regis.rex_json.load_file(changes_cache_filepath)
  
  if not branch in cached_changes:
    cached_changes[branch] = []

  changes_in_branch = cached_changes[branch]

  for file in files:
    if file not in changes_in_branch:
      changes_in_branch.append(file)
      print(f"adding file")

  regis.rex_json.save_file(changes_cache_filepath, cached_changes)   

def get_cached_changes(branch):
  changes_cache_filepath = os.path.join(regis.util.find_root(), changes_cache_filepath)

  if os.path.exists(changes_cache_filepath):
    cached_changes = regis.rex_json.load_file(changes_cache_filepath)
    local_branch = branch
    
    if local_branch in cached_changes:
      return cached_changes[local_branch]
    
  return []