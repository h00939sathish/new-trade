import importlib
import inspect
import pkgutil

from src.strategies.base import Strategy

# This will hold dynamically discovered strategy classes
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def load_strategies():
    """Dynamically loads all Strategy classes from the src.strategies package."""
    import src.strategies as strategies_pkg

    ignore_list = ["ml_regime", "pca_statarb", "sideways_reversion", "stat_arb", "tsmom"]

    for _, module_name, is_pkg in pkgutil.iter_modules(strategies_pkg.__path__):
        if is_pkg or module_name == "base" or module_name in ignore_list:
            continue

        module = importlib.import_module(f"src.strategies.{module_name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Strategy) and obj is not Strategy:
                # We need to instantiate it temporarily to get its name, or look for a name attribute.
                # Assuming the class sets `name` in __init__, we must mock it or check class variables.
                # Since existing strategies set `self.name` in __init__, we will just instantiate them with defaults.
                try:
                    # Instantiate to get the .name attribute
                    instance = obj()
                    registry_key = getattr(instance, "name", name)
                except Exception:
                    registry_key = name

                STRATEGY_REGISTRY[registry_key] = obj

load_strategies()
