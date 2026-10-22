"""Optional NumPy installation plans and atomic activation; no Maya or Qt imports."""
import importlib.util
import json
import os
import re
import shutil
import struct
import sys
import sysconfig
import tempfile
import uuid

NUMPY_VERSION='1.26.4'
ENV_MARKER='RTK_LAYER_SKIN_PYTHON='
NUMPY_MARKER='RTK_LAYER_SKIN_NUMPY='

ENV_PROBE="""import importlib.util,json,struct,sys,sysconfig
print('RTK_LAYER_SKIN_PYTHON='+json.dumps(dict(python=list(sys.version_info[:2]),platform=sysconfig.get_platform(),bits=struct.calcsize('P')*8,pip=importlib.util.find_spec('pip') is not None)))
"""
NUMPY_PROBE="""import json,os,sys
sys.path.insert(0,sys.argv[1])
import numpy as np
a=np.array([0.,.5,1.],dtype=np.float64)
assert bool(np.all(np.abs(a-a)<=1e-7))
print('RTK_LAYER_SKIN_NUMPY='+json.dumps(dict(version=np.__version__,file=os.path.realpath(np.__file__))))
"""


def runtime_info():
    return dict(python=list(sys.version_info[:2]),platform=sysconfig.get_platform(),bits=struct.calcsize('P')*8)


def supported(info=None):
    version=tuple((info or runtime_info())['python'])
    return (3,9)<=version<(3,13)


def dependency_root(user_directory):
    if not isinstance(user_directory,str) or not user_directory.strip():
        raise ValueError('Maya user folder is unavailable.')
    info=runtime_info()
    tag='py{}_{}-{}-{}'.format(*info['python'],info['platform'],info['bits'])
    tag=re.sub(r'[^a-zA-Z0-9_.-]','_',tag)
    return os.path.join(os.path.abspath(user_directory),'layer_skin_packages',tag)


def mayapy_path(environ=None,executable=None):
    environ=os.environ if environ is None else environ
    executable=sys.executable if executable is None else executable
    candidates=[]
    if os.path.basename(executable).lower() in ('mayapy','mayapy.exe'):candidates.append(executable)
    location=environ.get('MAYA_LOCATION')
    names=('mayapy.exe','mayapy') if os.name=='nt' else ('mayapy','mayapy.exe')
    if location:candidates.extend(os.path.join(location,'bin',name) for name in names)
    directory=os.path.dirname(executable)
    candidates.extend(os.path.join(directory,name) for name in names)
    candidates.extend(os.path.join(os.path.dirname(directory),'bin',name) for name in names)
    return next((os.path.abspath(path) for path in candidates if os.path.isfile(path)),None)


def parse_result(output,marker):
    for line in reversed(output.splitlines()):
        if line.startswith(marker):
            result=json.loads(line[len(marker):])
            if isinstance(result,dict):return result
    raise ValueError('Maya Python did not return its verification result. See install details.')


def validate_runtime(result):
    if any(result.get(key)!=value for key,value in runtime_info().items()):
        raise ValueError('The located mayapy does not match this Maya Python version or platform.')
    if not result.get('pip'):
        raise ValueError('pip is unavailable in Maya Python. Repair its pip installation, then retry.')


def _child(root,path):
    root=os.path.realpath(root);path=os.path.realpath(path)
    return os.path.dirname(path)==root and path!=root


def active_path(root):
    if not root:return None
    try:
        with open(os.path.join(root,'active.json'),encoding='utf-8') as stream:
            data=json.loads(stream.read(8193))
        name=data['directory']
        if data['version']!=NUMPY_VERSION or not isinstance(name,str):return None
        if not re.fullmatch(r'numpy-1\.26\.4-[0-9a-f]{32}',name):return None
        path=os.path.join(root,name)
        if _child(root,path) and os.path.isfile(os.path.join(path,'numpy','__init__.py')):return path
    except (OSError,ValueError,TypeError,KeyError):pass
    return None


def make_stage(root):
    os.makedirs(root,exist_ok=True)
    return tempfile.mkdtemp(prefix='.numpy-install-',dir=root)


def remove_stage(root,path):
    if not path:return
    if not _child(root,path) or not os.path.basename(path).startswith('.numpy-install-') or os.path.islink(path):
        raise ValueError('Refusing to remove a folder outside this install attempt.')
    if os.path.isdir(path):shutil.rmtree(path)


def pip_arguments(stage):
    return ['-m','pip','install','--disable-pip-version-check','--no-input',
            '--only-binary=:all:','--no-deps','--progress-bar','off',
            '--timeout','30','--retries','1','--target',stage,'numpy=='+NUMPY_VERSION]


def verify_numpy(result,stage):
    if result.get('version')!=NUMPY_VERSION:
        raise ValueError('Maya Python did not load the requested NumPy version.')
    actual=os.path.realpath(result.get('file',''))
    expected=os.path.realpath(os.path.join(stage,'numpy','__init__.py'))
    if actual!=expected:raise ValueError('Verification loaded NumPy outside the new installation.')


def activate(root,stage):
    """Publish only a successfully verified staging folder; keep prior installs."""
    if not _child(root,stage) or not os.path.basename(stage).startswith('.numpy-install-') or os.path.islink(stage):
        raise ValueError('Invalid NumPy staging folder.')
    if not os.path.isfile(os.path.join(stage,'numpy','__init__.py')):raise ValueError('NumPy installation is incomplete.')
    name='numpy-'+NUMPY_VERSION+'-'+uuid.uuid4().hex
    target=os.path.join(root,name);temporary=None
    os.replace(stage,target)
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='.active-',suffix='.json',dir=root,delete=False) as stream:
            temporary=stream.name
            json.dump(dict(version=NUMPY_VERSION,directory=name),stream)
        os.replace(temporary,os.path.join(root,'active.json'))
    except Exception:
        shutil.rmtree(target,ignore_errors=True)
        if temporary and os.path.isfile(temporary):os.remove(temporary)
        raise
    return target
