"""
RoboClaw - An embodied intelligence assistant framework
"""

__version__ = "0.1.0"
__logo__ = "🤖"


def _register_vendored_packages() -> None:
    """Make vendored packages importable by their original names."""
    import importlib
    import sys

    if "scservo_sdk" not in sys.modules:
        try:
            mod = importlib.import_module("roboclaw.vendor.scservo_sdk")
            sys.modules["scservo_sdk"] = mod
        except ImportError:
            pass


_register_vendored_packages()
