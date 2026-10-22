"""Path-aware launcher. Run this file with runpy; no forced unload or Undo reset."""
import ast
import os


def registered_plugin(cmds):
    """Find the owner of the registered command, including a renamed plug-in."""
    for name in cmds.pluginInfo(query=True,listPlugins=True) or []:
        if 'rtkLayerSkin' in (cmds.pluginInfo(name,query=True,command=True) or []):
            return dict(name=name,path=cmds.pluginInfo(name,query=True,path=True),
                        version=cmds.pluginInfo(name,query=True,version=True))
    return None


def disk_version(path):
    with open(path,encoding='utf-8') as stream:tree=ast.parse(stream.read(),filename=path)
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets):
            version=ast.literal_eval(node.value)
            if isinstance(version,str):return version
    raise ValueError('Cannot find the Layer Skin VERSION in '+path)


def open_ui(folder=None,cmds=None):
    if cmds is None:
        import maya.cmds as cmds
    folder=os.path.abspath(folder or os.path.dirname(__file__))
    files=('layer_skin_test.py','layer_skin_core.py','layer_skin_assignment.py','layer_skin_session.py',
           'layer_skin_joint_view.py','layer_skin_workflow_ui.py','layer_skin_ui.py','layer_skin_artisan.py')
    missing=[name for name in files if not os.path.isfile(os.path.join(folder,name))]
    if missing:raise RuntimeError('Extract the complete layer_skin_prototype folder. Missing: '+', '.join(missing))
    path=os.path.join(folder,'layer_skin_test.py');expected=disk_version(path)
    loaded=registered_plugin(cmds)
    if loaded is None:
        cmds.loadPlugin(path,quiet=True)
        loaded=registered_plugin(cmds)
    if loaded is None:raise RuntimeError('The plug-in did not register rtkLayerSkin: '+path)
    same_path=os.path.normcase(os.path.realpath(loaded['path']))==os.path.normcase(os.path.realpath(path))
    if not same_path or loaded['version']!=expected:
        raise RuntimeError('Layer Skin registered version {version} from {path}; requested version {expected} from {requested}. '
            'The registered plug-in and this folder do not match. No unload or Undo reset was performed. '
            'Use the matching folder, or load the requested folder in a fresh Maya session.'.format(
                expected=expected,requested=path,**loaded))
    print('Layer Skin {version} | {path}'.format(**loaded))
    return cmds.rtkLayerSkin(action='ui')


if __name__=='__main__':open_ui()
