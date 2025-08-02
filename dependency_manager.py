import os
import sys
import subprocess
import importlib

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CHECK_FILE_NAME = ".dependencies_checked"
CHECK_FILE_PATH = os.path.join(PLUGIN_DIR, CHECK_FILE_NAME)

REQUIRED_PACKAGES = [
    ("requests", "requests"),
    ("PIL", "Pillow")
]

def _log_info(message):
    print(f"[RemixConnector DependencyManager] INFO: {message}")

def _log_warning(message):
    print(f"[RemixConnector DependencyManager] WARN: {message}")

def _log_error(message):
    print(f"[RemixConnector DependencyManager] ERROR: {message}")

def _get_painter_python_executable():
    try:
        painter_base_dir = os.path.dirname(sys.executable)
        
        potential_paths = [
            os.path.join(painter_base_dir, "resources", "pythonsdk", "python.exe"),
            os.path.join(painter_base_dir, "python", "bin", "python3"),
            os.path.join(painter_base_dir, "Contents", "Resources", "pythonsdk", "bin", "python"),
            os.path.join(painter_base_dir, "pythonsdk", "python"),
        ]
        
        for py_sdk_path in potential_paths:
            if os.path.isfile(py_sdk_path):
                _log_info(f"Found Painter Python SDK at: {py_sdk_path}")
                return py_sdk_path
        
        _log_warning("Painter's python executable not found in typical locations.")
        return "python.exe" 
    except Exception as e:
        _log_error(f"Error detecting Painter's Python executable: {e}. Falling back to 'python.exe'.")
        return "python.exe"

def _install_package(package_name):
    py_exe = _get_painter_python_executable()

    if not py_exe or (not os.path.isfile(py_exe) and py_exe != "python.exe"):
        _log_error(f"Could not find a valid Python executable to install '{package_name}'. Path given: '{py_exe}'")
        return False

    command = [py_exe, "-m", "pip", "install", "--quiet", package_name]
    _log_info(f"Running installation command: {' '.join(command)}")
    
    try:
        startupinfo, creationflags = None, 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
            
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, 
            startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore'
        )
        _log_info(f"'{package_name}' installation seems successful.")
        if result.stdout:
             _log_info(f"Pip stdout: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        _log_error(f"Failed to run pip. Make sure '{py_exe}' is a valid Python executable with pip available.")
        return False
    except subprocess.CalledProcessError as e:
        _log_error(f"Pip install failed for '{package_name}'. Return Code: {e.returncode}")
        if e.stdout: _log_error(f"Pip stdout:\n{e.stdout.strip()}")
        if e.stderr: _log_error(f"Pip stderr:\n{e.stderr.strip()}")
        return False
    except Exception as e:
        _log_error(f"An unexpected error occurred during '{package_name}' installation: {e}")
        return False

def _check_dependency(import_name, package_name):
    try:
        importlib.import_module(import_name)
        _log_info(f"Dependency '{import_name}' is already installed.")
        return True
    except ImportError:
        _log_warning(f"Dependency '{import_name}' not found. Attempting to install '{package_name}'...")
        if _install_package(package_name):
            importlib.invalidate_caches()
            try:
                importlib.import_module(import_name)
                _log_info(f"Successfully installed and verified '{import_name}'.")
                return True
            except ImportError:
                _log_error(f"Failed to import '{import_name}' even after installation.")
                return False
        else:
            return False

def ensure_dependencies_installed(force_check=False):
    _log_info("Starting dependency check...")

    if not force_check and os.path.exists(CHECK_FILE_PATH):
        _log_info("Dependency check already performed (marker file found). Skipping.")
        return True

    all_ok = True
    for import_name, package_name in REQUIRED_PACKAGES:
        if not _check_dependency(import_name, package_name):
            all_ok = False
            _log_error(f"Failed to ensure dependency '{package_name}' is installed.")
    
    if all_ok:
        _log_info("All dependencies are met.")
        try:
            with open(CHECK_FILE_PATH, 'w') as f:
                f.write("Dependency check completed successfully.")
            _log_info(f"Created marker file: {CHECK_FILE_PATH}")
        except IOError as e:
            _log_warning(f"Could not create dependency marker file: {e}")
        return True
    else:
        _log_error("One or more required dependencies could not be installed. The plugin may not function correctly.")
        return False
