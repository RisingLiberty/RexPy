import time
import regis.diagnostics

class TaskRaiiPrint(object):
  def __init__(self, msg):
    self._msg = msg
    self._finished_msg = "done"
    self.start_time = time.time()
  
  def failed(self):
    self._finished_msg = "failed"

  def __enter__(self):
    regis.diagnostics.log_info(self._msg)
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    end_time = time.time()
    regis.diagnostics.log_info(f"{self._msg} - {self._finished_msg}")
    regis.diagnostics.log_info(f"  took {end_time - self.start_time:0.2f} seconds")

    