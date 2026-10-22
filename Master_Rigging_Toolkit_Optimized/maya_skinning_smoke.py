"""Explicit native Maya checks. Creates/cleans its own namespace, never opens a scene."""
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya_copy_skinning_smoke as demo_tools


def run():
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo first.')
    api=demo_tools.load();editor=api.load_editor();adapter=api.editor_api()
    selection=om.MGlobal.getActiveSelectionList();namespace=cmds.namespaceInfo(currentNamespace=True);demo=demo_tools.make_demo()
    try:
        ctx=api.context(demo['target']);influences=ctx['influences']
        aid=om.MFnDependencyNode(api.object_(demo['joints'][0])).uuid().asString();a=next(i for i,r in enumerate(influences) if r['uuid']==aid)
        b=1-a;bid=influences[b]['uuid'];width=ctx['width']
        def weights():return api.context(demo['target'])['weights']
        def close(actual,expected):assert api.same(actual,expected,2e-6),(actual,expected)
        def set_rows(values):
            ordered=[]
            for av,bv in values:
                row=[0.,0.];row[a]=av;row[b]=bv;ordered.extend(row)
            ctx['fn'].setWeights(ctx['dag'],api.components(range(3)),om.MIntArray(range(width)),om.MDoubleArray(ordered),False)
        def command(action,**kw):
            data=dict(operation='edit',action=action,mesh=demo['target'],influences=[aid],value=.25)
            data.update(kw);return json.loads(cmds.rtkCopySkin(data=json.dumps(data)))
        # Vertex/face/edge scopes resolve without changing the active selection.
        for components,expected in ((demo['target']+'.vtx[0:1]',[0,1]),(demo['target']+'.f[0]',[0,1,2])):
            cmds.select(components,replace=True);before=cmds.ls(selection=True,flatten=True)
            assert editor.selected_vertices(adapter,ctx)==expected
            assert cmds.ls(selection=True,flatten=True)==before
        cmds.select(demo['target']+'.e[0]',replace=True);assert len(editor.selected_vertices(adapter,ctx))==2
        cmds.select(demo['target']+'.vtx[0:1]',replace=True);before=weights()
        planned=api.edit_plan(dict(mesh=demo['target'],action='set',influences=[aid],value=.25),progress=True)
        close(weights(),before);assert planned['vertices']==[0,1]
        result=command('set');assert result['changed_vertices']==2;after=weights()
        close([after[a],after[width+a],after[2*width+a]],[.25,.25,0])
        cmds.undo();close(weights(),before)
        cmds.redo();close(weights(),after)
        cmds.undo();close(weights(),before)
        # Copy multiple source vertices: mean is 1/3, 2/3, not their sum.
        cmds.select(demo['source']+'.vtx[*]',replace=True)
        copied=editor.clipboard(adapter,demo['source'])
        value=next(r['weight'] for r in copied['influences'] if r['uuid']==aid);assert abs(value-1/3)<2e-6
        cmds.select(demo['target']+'.vtx[2]',replace=True);command('paste',clipboard=copied)
        close([weights()[2*width+a],weights()[2*width+b]],[1/3,2/3]);cmds.undo();close(weights(),before)
        # Held values are preserved; changes to Hold are explicit and undoable.
        set_rows([(.4,.6)]*3)
        editor.set_hold(adapter,demo['target'],[bid],'hold');assert cmds.getAttr(influences[b]['path']+'.lockInfluenceWeights')
        cmds.select(demo['target']+'.vtx[0]',replace=True);before=weights();result=command('nudge',value=.9)
        assert result['changed_vertices']==0;close(weights(),before)
        editor.set_hold(adapter,demo['target'],[bid],'unhold');assert not cmds.getAttr(influences[b]['path']+'.lockInfluenceWeights')
        cmds.undo();assert cmds.getAttr(influences[b]['path']+'.lockInfluenceWeights')
        cmds.redo();assert not cmds.getAttr(influences[b]['path']+'.lockInfluenceWeights')
        # One-ring smoothing reads a consistent original snapshot.
        set_rows([(.1,.9),(.3,.7),(.5,.5)]);before=weights();command('smooth')
        close([weights()[a],weights()[b]],[.4,.6]);cmds.undo();close(weights(),before)
        command('average');close([weights()[a],weights()[b]],[.4,.6]);cmds.undo();close(weights(),before)
        set_rows([(.001,.999),(.3,.7),(.5,.5)]);command('prune',threshold=.01)
        close([weights()[a],weights()[b]],[0,1]);cmds.undo()
        # Distinct left/right skeleton and asymmetric weights test real mirrored columns.
        cmds.namespace(setNamespace=':');joint_paths=[]
        for name,x in (('mirror_L',1),('mirror_R',-1)):
            joint=cmds.createNode('joint',name=demo['namespace']+':'+name,parent=demo['root']);cmds.setAttr(joint+'.translateX',x);joint_paths.append(joint)
        mesh=cmds.polyCreateFacet(name=demo['namespace']+':mirrorMesh',point=[(-1,0,0),(1,0,0),(1,1,0)],constructionHistory=False)[0]
        mesh=cmds.parent(mesh,demo['root'])[0];skin=cmds.skinCluster(joint_paths,mesh,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        for joint in joint_paths:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        mirror_ctx=api.context(mesh);left_id=om.MFnDependencyNode(api.object_(joint_paths[0])).uuid().asString()
        left_column=next(i for i,r in enumerate(mirror_ctx['influences']) if r['uuid']==left_id);right_column=1-left_column
        row=[0.,0.];row[left_column]=1.
        mirror_ctx['fn'].setWeights(mirror_ctx['dag'],api.components(range(3)),om.MIntArray([0,1]),om.MDoubleArray(row*3),False)
        before=api.context(mesh)['weights'];cmds.select(mesh,replace=True)
        result=json.loads(cmds.rtkCopySkin(data=json.dumps(dict(operation='edit',action='mirror',mesh=mesh,geometry='current',axis=0,direction=1))))
        assert result['changed_vertices']==1
        after=api.context(mesh)['weights'];assert abs(after[right_column]-1)<2e-6
        assert after[2:]==before[2:],'Mirror must keep source-side vertices'
        cmds.undo();close(api.context(mesh)['weights'],before)
        print('Skinning Tools native checks: PASS (scope, mean clipboard, bulk edit, held weights, smooth, prune, mirror and Undo/Redo). Test UI and actual Escape input manually.')
    finally:
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);om.MGlobal.setActiveSelectionList(selection)
