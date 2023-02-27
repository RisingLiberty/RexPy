import re
import subprocess
import rexpy.diagnostics

def __has_word(line, word : str):
  regex_str = f"({word.lower()})[\]}} \)\:]|({word.upper()})[\]}} \)\:]"
  result = re.findall(regex_str, line)
  return len(result) > 0

def __has_error(line : str):
  return __has_word(line, "error") or __has_word(line, "errors") or __has_word(line, "failed")

def __has_warning(line):
  return __has_word(line, "warning") or __has_word(line, "warnings")

def __build_output_callback(output : bytes):
  for line in iter(output.readline, b''):
    new_line : str = line.decode('UTF-8')
    if new_line.endswith('\n'):
      new_line = new_line.removesuffix('\n')

    if __has_error(new_line):
      rexpy.diagnostics.log_err(new_line)
    elif __has_warning(new_line):
      rexpy.diagnostics.log_warn(new_line)
    else:
      rexpy.diagnostics.log_no_color(new_line)

def run(cmd):
  proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
  __build_output_callback(proc.stdout)
  return proc
