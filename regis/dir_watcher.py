import os
import time
import watchdog.observers as ob
from enum import Enum, auto
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, RegexMatchingEventHandler, FileSystemEvent, FileSystemMovedEvent

ob.read_directory_changes.WATCHDOG_TRAVERSE_MOVED_DIR_DELAY = 0

class FileOperation(Enum):
    Open = 0
    Close = auto()
    Created = auto()
    Moved = auto()
    Modified = auto()
    Deleted = auto()

class Operation():
    def __init__(self, filepath : str, op : FileOperation, time : str):
        self.filepath = filepath
        self.op = op
        self.time = time

    def __str__(self):
        return f'[{self.time}][{self.op.name}] {self.filepath}'

class DirWatcher():
    def __init__(self, dir : str, bRecursive : bool):
        self.event_handler = FileSystemEventHandler()

        self.event_handler.on_created = self._on_created
        self.event_handler.on_deleted = self._on_deleted
        self.event_handler.on_modified = self._on_modified
        self.event_handler.on_moved = self._on_moved
        self.event_handler.on_opened = self._on_opened
        self.event_handler.on_closed = self._on_closed

        self.observer = Observer()
        self.observer.schedule(self.event_handler, dir, recursive=bRecursive)

        self.operations : list[Operation] = []

    def __enter__(self):
        self.observer.start()       
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.observer.stop()
        self.observer.join()

    def _on_created(self, event : FileSystemEvent):
        full_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))
        self.operations.append(Operation(full_path, FileOperation.Created, time.asctime()))
    
    def _on_deleted(self, event : FileSystemEvent):
        full_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))
        self.operations.append(Operation(full_path, FileOperation.Deleted, time.asctime()))
    
    def _on_modified(self, event : FileSystemEvent):
        full_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))
        self.operations.append(Operation(full_path, FileOperation.Modified, time.asctime()))
    
    def _on_moved(self, event : FileSystemMovedEvent):
        full_dest_path = os.path.normpath(os.path.join(os.getcwd(), event.dest_path))
        full_src_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))

        self.operations.append(Operation(f'{full_src_path} -> {full_dest_path}', FileOperation.Moved, time.asctime()))
        
    def _on_opened(self, event : FileSystemEvent):
        full_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))
        self.operations.append(Operation(full_path, FileOperation.Open, time.asctime()))

    def _on_closed(self, event : FileSystemEvent):
        full_path = os.path.normpath(os.path.join(os.getcwd(), event.src_path))
        self.operations.append(Operation(full_path, FileOperation.Close, time.asctime()))

