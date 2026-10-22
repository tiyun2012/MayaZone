"""Run after refreshing Layer Skin UI 25. Uses a temporary owned fixture."""
import importlib.util
from pathlib import Path

import maya.cmds as cmds
import maya.api.OpenMaya as om

import maya_layer_skin_demo


def run(keep=False):
    path=Path(__file__).with_name('layer_skin_test.py')
    spec=importlib.util.spec_from_file_location('_layer_skin_predeform_native_helper',str(path))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);api=helper.editor_api()
    geometry=helper.sibling('layer_skin_assignment');scene=helper.sibling('layer_skin_assignment_scene')
    selected=cmds.ls(selection=True,long=True) or [];demo=maya_layer_skin_demo.make_demo()
    def capture():
        ctx=api.context(demo['mesh']);return ctx,scene.capture_reference(vars(helper),ctx)
    def near(a,b):return len(a)==len(b) and all(abs(x-y)<3e-6*max(1.,abs(x),abs(y)) for x,y in zip(a,b))
    try:
        ctx,neutral=capture()
        visible=[list(p)[:3] for p in ctx['mesh'].getPoints(om.MSpace.kWorld)]
        cmds.setAttr(demo['root']+'.translateX',17.)
        cmds.setAttr(demo['root']+'.rotateZ',27.)
        cmds.setAttr(demo['root']+'.scale',1.4,1.4,1.4,type='double3')
        cmds.setAttr(demo['joints'][1]+'.rotateY',43.)
        ctx,posed=capture()
        assert any(not near(a,b) for a,b in zip(visible,[list(p)[:3] for p in ctx['mesh'].getPoints(om.MSpace.kWorld)]))
        assert all(near(a,b) for a,b in zip(neutral['points'],posed['points']))
        for identity in ctx['ids']:
            for name in ('position','x','y','z'):
                assert near(neutral['joints'][identity][name],posed['joints'][identity][name])
        for method in ('point','bone','axis'):
            cache=geometry.AssignmentCache();settings=dict(method=method,radius=4.)
            a,_=cache.generate(neutral,ctx['ids'],ctx['ids'],settings)
            b,_=cache.generate(posed,ctx['ids'],ctx['ids'],settings)
            assert set(a)==set(b)
            for vertex in a:
                assert near(a[vertex]['weights'],b[vertex]['weights'])
                assert abs(a[vertex]['coverage']-b[vertex]['coverage'])<3e-6
        report=dict(passed=True,checks=['visible posed geometry differs','skin input positions stay fixed',
            'joint bind frames stay fixed','point/bone/axis assignments agree across poses'],fixture=demo['root'],kept=keep)
        print('Layer Skin predeform smoke:',report);return report
    finally:
        if not keep:
            nodes=cmds.ls(demo['namespace']+':*',long=True) or []
            if nodes:cmds.delete(nodes)
            if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'])
        remaining=[node for node in selected if cmds.objExists(node)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)
