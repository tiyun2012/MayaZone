"""Native Maya check after opening/refreshing Layer Skin UI 27. No new scene."""
import importlib.util
import json
from pathlib import Path
import uuid

import maya.cmds as cmds


def run(keep=False):
    if not hasattr(cmds,'rtkLayerSkin'):raise RuntimeError('Open Layer Skin UI 27 before running the hierarchy test.')
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Maya Undo before testing.')
    path=Path(__file__).with_name('layer_skin_test.py')
    spec=importlib.util.spec_from_file_location('_layer_skin_hierarchy_native_helpers',str(path))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);api=helper.editor_api()
    prefix='layerHierarchySmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True);selected=cmds.ls(selection=True,long=True) or []
    fixture=None;meta=None;skin=None
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        fixture=cmds.createNode('transform',name=prefix+':fixture',skipSelect=True)
        root=cmds.createNode('joint',name=prefix+':root',parent=fixture,skipSelect=True)
        cmds.xform(root,worldSpace=True,translation=(-5.,0.,0.));root=cmds.ls(root,long=True)[0]
        joints=[root];tips=[]
        for side,y,count in (('left',10.,1),('right',-10.,3)):
            parent=root
            for index in range(count):
                parent=cmds.createNode('transform',name=prefix+':'+side+'Buffer'+str(index),parent=parent,skipSelect=True)
            joint=cmds.createNode('joint',name=prefix+':joint',parent=parent,skipSelect=True)
            cmds.xform(joint,worldSpace=True,translation=(0.,y,0.));joint=cmds.ls(joint,long=True)[0];joints.append(joint)
            buffer=cmds.createNode('transform',name=prefix+':'+side+'TipOffset',parent=joint,skipSelect=True)
            tip=cmds.createNode('joint',name=prefix+':tip',parent=buffer,skipSelect=True)
            cmds.xform(tip,worldSpace=True,translation=(2.,y,0.));tip=cmds.ls(tip,long=True)[0];joints.append(tip);tips.append(tip)
        mesh=cmds.polyCreateFacet(point=[(3.,10.,0.),(3.,-10.,0.),(-8.,0.,0.)],constructionHistory=False,name=prefix+':mesh')[0]
        mesh=cmds.parent(mesh,fixture)[0]
        skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False,name=prefix+':skin')[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        for joint in joints:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        cmds.skinPercent(skin,mesh,transformValue=[(joint,1. if joint==root else 0.) for joint in joints],normalize=True)
        poses={joint:cmds.xform(joint,query=True,worldSpace=True,matrix=True) for joint in joints}
        def call(action,**data):return cmds.rtkLayerSkin(action=action,data=json.dumps(dict(target=mesh,**data)))
        def read():
            ctx=api.context(mesh);node,state=api.metadata(ctx);return ctx,node,state
        call('add',name='Branch assignment');ctx,meta,state=read();layer=state['layers'][0]['id'];before=ctx['weights'][:]
        call('assign',layer=layer,joints=list(reversed(ctx['ids'])),whole=True,settings=dict(method='axis'))
        ctx,meta,state=read();reference=state['reference']
        assert reference.get('hierarchy_version')==1,'Run layer_skin_ui_refresh.py from UI 27 before this test.'
        assert len(reference['joints'][api.joint_id(root)]['ends'])==2
        assert state['layers'][0]['assignment']['settings']['rule']=='nearest_bone_axis_ties'
        assert state['layers'][0]['assignment']['assigned_vertices']==3
        assert state['layers'][0]['generated']['2']['coverage']==1.,'Negative-side vertex was left unassigned'
        for vertex,joint in enumerate([tips[0],tips[1],root]):
            column=ctx['ids'].index(api.joint_id(joint))
            assert abs(ctx['weights'][vertex*len(ctx['ids'])+column]-1.)<2e-6,(vertex,joint)
        assigned=ctx['weights'][:]
        cmds.undo();assert api.same(read()[0]['weights'],before,2e-6)
        cmds.redo();assert api.same(read()[0]['weights'],assigned,2e-6)
        for method in ('point','bone'):
            call('assign',layer=layer,joints=ctx['ids'],whole=True,settings=dict(method=method))
            ctx,meta,state=read();assert state['layers'][0]['assignment']['assigned_vertices']==3
            assert api.same(ctx['weights'],assigned,2e-6),(method,ctx['weights'])
        for joint,pose in poses.items():assert api.same(cmds.xform(joint,query=True,worldSpace=True,matrix=True),pose,2e-6)
        report=dict(passed=True,checks=['duplicate leaf names','buffered branches','nearest joint/bone/axis',
                    'frozen endpoints','negative-side full coverage','native Undo/Redo','joint pose retained'],fixture=fixture,kept=keep)
        print('Layer Skin hierarchy smoke:',report);return report
    finally:
        if not keep:
            for node in (meta,fixture,skin):
                if node and cmds.objExists(node):cmds.delete(node)
            if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=namespace)
        remaining=[node for node in selected if cmds.objExists(node)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)
