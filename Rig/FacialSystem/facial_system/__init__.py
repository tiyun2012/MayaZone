"""One entry point for the stock-node Maya Facial System.

Importing this package alone does not import Maya, open a window, or edit a scene.
"""
__version__ = '1.2.0'


def show(step=None):
    """Open/reuse the workflow window. Steps: setup, groups, wrap, fit, check."""
    from .ui import show as open_window
    return open_window(step=step)


def reload_ui(step=None):
    """Reload this package after replacing files; keep unsaved data protected."""
    import importlib
    import sys
    old = sys.modules.get(__name__ + '.ui')
    if old is not None and not old.close_window():
        return None
    importlib.invalidate_caches()
    importlib.reload(sys.modules[__name__])
    for name in ('core', 'scene_adapter', 'fit', 'cage_landmarks', 'cage_core', 'cage', 'project', 'scene_ops',
                 'validation', 'neutral_editor', 'landmark_ui', 'cage_ui', 'ui'):
        full = __name__ + '.' + name
        if full in sys.modules:
            importlib.reload(sys.modules[full])
    return show(step=step)


def load_neutral(path):
    from .core import load
    return load(path)


def preview_fit(document, mapping, **kwargs):
    from .fit import preview
    return preview(document, mapping, **kwargs)


def apply_fit(document, mapping, **kwargs):
    from .fit import apply
    return apply(document, mapping, **kwargs)


def check_rig(limit=None, progress=None):
    from .validation import check_behavior
    return check_behavior(limit=limit, progress=progress)


def check_fit(document, mapping, install_mesh=True, reset=False):
    from .validation import check_fit as verify
    return verify(document, mapping, install_mesh=install_mesh, reset=reset)
