"""Drop this file into Maya's viewport, or run it as a Python script."""
from pathlib import Path
import sys


def launch(folder=None):
    if folder is None:
        script = globals().get('__file__')
        if script:
            folder = Path(script).resolve().parent
        else:
            import maya.cmds as cmds
            chosen = cmds.fileDialog2(fileMode=3, caption='Choose the extracted FacialSystem folder') or []
            if not chosen:
                return None
            folder = Path(chosen[0])
    folder = Path(folder).expanduser().resolve()
    if not (folder / 'facial_system' / '__init__.py').is_file():
        raise ValueError('Choose the folder containing the facial_system package')
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    import facial_system
    return facial_system.show()


def onMayaDroppedPythonFile(*args):
    return launch()


if __name__ == '__main__':
    launch()
