import os

import regis.util
import regis.rex_json
import regis.diagnostics

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

def get_unstaged_files():
  cmd = 'git diff --name-only --no-ext-diff'
  output, errc = regis.util.run_and_get_output(cmd)
  return __zsplit(output)

def get_local_branchname():
  cmd = 'git rev-parse --abbrev-ref HEAD'
  output, errc = regis.util.run_and_get_output(cmd)
  return output.strip('\n')

def cache_commit_changes(branch : str, files : list[str]):
  full_changes_cache_filepath = os.path.join(regis.util.find_root(), changes_cache_filepath)

  cached_changes = {}
  if os.path.exists(full_changes_cache_filepath):
    cached_changes = regis.rex_json.load_file(full_changes_cache_filepath)
  
  if not branch in cached_changes:
    cached_changes[branch] = []

  changes_in_branch = cached_changes[branch]

  for file in files:
    if file not in changes_in_branch:
      changes_in_branch.append(file)
      print(f"adding file")

  regis.rex_json.save_file(changes_cache_filepath, cached_changes)   

def get_cached_changes(branch):
  full_changes_cache_filepath = os.path.join(regis.util.find_root(), changes_cache_filepath)

  if os.path.exists(full_changes_cache_filepath):
    cached_changes = regis.rex_json.load_file(full_changes_cache_filepath)
    local_branch = branch
    
    if local_branch in cached_changes:
      return cached_changes[local_branch]
    
  return []

def stash_uncommitted_changes(stashName):
  cmd = f"git stash save {stashName} -k"
  output, errc = regis.util.run_and_get_output(cmd)
  regis.diagnostics.log_no_color(output)
  return output

def unstash(stashName):
  stash_idx, stash_branch, stash_name = find_stash(stashName)
  cmd = f"git stash apply {stash_idx}"
  output, errc = regis.util.run_and_get_output(cmd)
  regis.diagnostics.log_no_color(output)
  return output

def get_stash_list():
  cmd = f"git stash list"
  output, errc = regis.util.run_and_get_output(cmd)
  return __zsplit(output)

def find_stash(stashName):
  stashes = get_stash_list()
  branch_name = get_local_branchname()
  
  # stash format: stash@{0}: On devops/githooks: pre-push
  for stash in stashes:
    colon_idx = stash.find(':')
    stash_idx = stash[0: colon_idx]
    num_to_skip = len(": On ")
    branch_start = colon_idx + num_to_skip
    colon_idx = stash.find(':', colon_idx + 1)
    stash_branch = stash[branch_start: colon_idx]
    num_to_skip = len(": ")
    name_start = colon_idx + num_to_skip
    stash_name = stash[name_start: len(stash)]

    if (stashName.lower() == stash_name.lower()):
      return stash_idx, stash_branch, stash_name
    
  return None, None, None

def remove_stash(stashName):
  stash_idx, stash_branch, stash_name = find_stash(stashName)
  cmd = f"git stash drop {stash_idx}"
  output, errc = regis.util.run_and_get_output(cmd)
  regis.diagnostics.log_no_color(output)
