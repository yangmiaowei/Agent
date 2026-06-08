import pkgutil
import importlib
import src.tools

def load_all_tools():
    for _, module_name, _ in pkgutil.iter_modules(src.tools.__path__):
        importlib.import_module(f"src.tools.{module_name}")