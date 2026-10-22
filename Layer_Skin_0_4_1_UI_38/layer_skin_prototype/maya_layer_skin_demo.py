"""Run inside Maya after loading layer_skin_test.py. No file/new-scene operations."""
import importlib.util
import json
import os
import uuid

import maya.cmds as cmds


def make_demo():
    """Create a small mesh with two independent joints; return created objects."""
    prefix = 'layerSkinDemo_' + uuid.uuid4().hex[:8]
    previous = cmds.namespaceInfo(currentNamespace=True)
    cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
    try:
        root = cmds.createNode('transform',name=prefix+':DEMO')
        joints=[]
        for label,x in (('left',-3),('right',3)):
            joint=cmds.createNode('joint',name=prefix+':'+label+'_JNT',parent=root)
            cmds.setAttr(joint+'.translateX',x);joints.append(joint)
        mesh=cmds.polyPlane(name=prefix+':mesh',width=8,height=2,subdivisionsX=8,subdivisionsY=2,constructionHistory=False)[0]
        mesh=cmds.parent(mesh,root)[0]
        skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,maximumInfluences=2,
                              obeyMaxInfluences=False,name=prefix+':skinCluster')[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        for joint in joints:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        cmds.skinPercent(skin,mesh,transformValue=[(joints[0],1),(joints[1],0)],normalize=True)
        cmds.select(mesh,replace=True)
        return {'namespace':prefix,'root':root,'mesh':mesh,'skin':skin,'joints':joints}
    finally:
        cmds.namespace(setNamespace=previous)


def run_smoke():
    """Native API/Undo test. Creates and cleans only its own temporary namespace."""
    if not cmds.undoInfo(query=True,state=True):
        raise RuntimeError('Enable Maya Undo first.')
    spec=importlib.util.spec_from_file_location('_layer_skin_native_helpers',os.path.join(os.path.dirname(__file__),'layer_skin_test.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    demo=make_demo();mesh=demo['mesh']
    def call(action,**data):
        data['target']=mesh
        return cmds.rtkLayerSkin(action=action,data=json.dumps(data))
    def read():
        ctx=helper.context(mesh);meta,state=helper.metadata(ctx)
        return ctx,meta,state
    def close(a,b):return helper.same(a,b,2e-6)
    try:
        before,_,_=read();base=before['weights'][:]
        width=len(before['ids']);right=next(i for i,p in enumerate(before['influences']) if p.fullPathName().endswith('right_JNT'))
        call('initialize');_,meta,state=read();assert meta and state['base']==base
        cmds.undo();assert read()[1] is None
        cmds.redo();assert read()[1] is not None
        call('add',name='Right region');layer=read()[2]['layers'][-1]['id']
        cmds.select([mesh+'.vtx[0:3]'],replace=True)
        call('flood',layer=layer,influence=right,value=1)
        flooded=read()[0]['weights']
        for v in range(4):assert abs(flooded[v*width+right]-1)<2e-6
        assert close(flooded[4*width:],base[4*width:])
        cmds.undo();assert close(read()[0]['weights'],base)
        cmds.redo();assert close(read()[0]['weights'],flooded)
        call('properties',layer=layer,opacity=.5)
        partial=read()[0]['weights']
        for v in range(4):assert abs(partial[v*width+right]-.5)<2e-6
        cmds.select(mesh+'.vtx[0]',replace=True)
        call('mask',layer=layer,value=0)
        masked=read()[0]['weights'];assert close(masked[:width],base[:width])
        assert close(masked[width:4*width],partial[width:4*width])
        call('properties',layer=layer,enabled=False);assert close(read()[0]['weights'],base)
        call('properties',layer=layer,enabled=True);assert close(read()[0]['weights'],masked)
        # One reorder command must update actual skin weights and Undo together.
        call('add',name='Order test');upper=read()[2]['layers'][-1]['id']
        cmds.select(mesh+'.vtx[1]',replace=True)
        call('flood',layer=upper,influence=1-right,value=1)
        upper_weights=read()[0]['weights'][:]
        call('reorder',order=[upper,layer]);reordered=read()[0]['weights'][:]
        assert not close(upper_weights[width:2*width],reordered[width:2*width])
        assert [r['id'] for r in read()[2]['layers']]==[upper,layer]
        cmds.undo();assert close(read()[0]['weights'],upper_weights)
        cmds.redo();assert close(read()[0]['weights'],reordered)
        call('delete',layer=upper);assert close(read()[0]['weights'],masked)
        ctx,_,state=read();assert helper.core.decode(helper.core.encode(state))==state
        cmds.setAttr(demo['joints'][1]+'.translateY',1)
        assert close(read()[0]['weights'],masked),'Animation must not recompose weights'
        # External edits are detected; bake retains them, restore explicitly replaces them.
        cmds.skinPercent(demo['skin'],mesh+'.vtx[0]',transformValue=[(demo['joints'][0],.7),(demo['joints'][1],.3)],normalize=True)
        external=read()[0]['weights']
        try:
            call('properties',layer=layer,opacity=.2)
        except RuntimeError:
            pass
        else:
            raise AssertionError('External edits were not detected')
        assert close(read()[0]['weights'],external)
        call('bake');assert read()[1] is None and close(read()[0]['weights'],external)
        cmds.undo();assert read()[1] is not None and close(read()[0]['weights'],external)
        call('restore');assert read()[1] is None and close(read()[0]['weights'],base)
        cmds.undo();assert read()[1] is not None and close(read()[0]['weights'],external)
        cmds.redo();assert read()[1] is None and close(read()[0]['weights'],base)
        print('PASS: native layer creation, selected-vertex Flood, opacity, masks, enable/disable, reorder, Undo/Redo, serialized data, external-edit protection, bake and restore.')
    finally:
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):
            cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def _helpers():
    path=os.path.join(os.path.dirname(__file__),'layer_skin_test.py')
    spec=importlib.util.spec_from_file_location('_layer_skin_workflow_native_helpers',path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    loaded=helper.sibling('layer_skin_launch').registered_plugin(cmds)
    if not loaded or loaded['version']!=helper.VERSION or os.path.normcase(os.path.realpath(loaded['path']))!=os.path.normcase(os.path.realpath(path)):
        raise RuntimeError('Registered Layer Skin: {}. Native tests require {} from {}. Use layer_skin_launch.py to inspect the mismatch.'.format(loaded,helper.VERSION,path))
    return helper


def run_array_feedback():
    """Maya API/Undo check of the new working array; visual brush check is manual.

    Simulates Artisan's native array write with an undoable setAttr between the
    real before/after hooks. Creates and cleans only its own demo namespace.
    """
    helper=_helpers();api=helper.editor_api();session=api.make_session()
    selection=cmds.ls(selection=True,long=True) or []
    demo=make_demo();mesh=demo['mesh']
    def read():
        ctx=helper.context(mesh);return ctx,helper.metadata(ctx)[1]
    def native_stroke(values):
        session.before_stroke()
        cmds.setAttr(session.buffer.attribute(),len(values),*values,type='doubleArray')
        session.after_stroke()
    try:
        cmds.rtkLayerSkin(action='add',data=json.dumps(dict(target=mesh,name='Array feedback')))
        ctx,state=read();layer=state['layers'][0]['id']
        first=helper.joint_id(demo['joints'][0]);second=helper.joint_id(demo['joints'][1])
        session.start(mesh,layer,joint=second,joint_path=demo['joints'][1],mode='weights')
        incoming=session.buffer.surface.connectedTo(True,False)
        assert len(incoming)==1 and incoming[0].node()==api.obj(session.target),'No geometry connection to the painted mesh'
        assert incoming[0].partialName(useLongNames=True)=='outMesh'
        assert cmds.artUserPaintCtx(api.paint_context,query=True,getArrayAttrCommand=True)=='rtkLSArray041'
        assert cmds.artUserPaintCtx(api.paint_context,query=True,setValueCommand=True) in ('',None,[])
        plug=session.buffer.attribute();before=helper.core.encode(read()[1])
        values=[0.]*ctx['count'];values[0]=.8;values[1]=.35
        native_stroke(values)
        assert session.last_stroke['status']=='saved' and session.last_stroke['layer_values_verified'],session.paint_report()
        after=helper.core.encode(read()[1])
        assert cmds.undoInfo(query=True,undoName=True).startswith('LayerSkinPaint_'),'The native array and layer command were not grouped'
        cmds.undo();assert helper.core.encode(read()[1])==before,'One Undo did not restore the layer'
        cmds.redo();assert helper.core.encode(read()[1])==after,'One Redo did not restore the layer'
        for _ in range(2):
            session.start(mesh,layer,joint=first,joint_path=demo['joints'][0],mode='weights')
            assert max(session.buffer.read())==0.
            session.start(mesh,layer,joint=second,joint_path=demo['joints'][1],mode='weights')
            assert helper.same(session.buffer.read(),values,2e-6)
            assert session.buffer.attribute()==plug,'View changes created additional working nodes'
        session.start(mesh,layer,mode='mask');mask=[1.]*ctx['count'];mask[0]=.25
        native_stroke(mask)
        session.start(mesh,layer,joint=second,mode='weights')
        session.start(mesh,layer,mode='mask',readonly=True)
        assert helper.same(session.buffer.read(),mask,2e-6)
        assert cmds.artUserPaintCtx(api.paint_context,query=True,opacity=True)==0.
        print('PASS: native working-array readback, grouped setAttr/layer Undo, joint/mask round trips and read-only opacity. Actual viewport color and real brush Undo still require a mouse-stroke check.')
    finally:
        session.close()
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        existing=[node for node in selection if cmds.objExists(node)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_authoring():
    """Native auto Base, frozen assignment, MEL brush bridge and influence-add Undo."""
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo first.')
    import maya.mel as mel
    helper=_helpers();api=helper.editor_api();session=api.make_session()
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    demo=make_demo();mesh=demo['mesh']
    def call(action,**data):return cmds.rtkLayerSkin(action=action,data=json.dumps(dict(target=mesh,**data)))
    def read():
        ctx=helper.context(mesh);return ctx,helper.metadata(ctx)[1]
    try:
        before=read()[0]['weights'][:]
        call('add',name='Authoring');ctx,state=read();layer=state['layers'][0]['id']
        assert state['base']==before
        cmds.undo();assert read()[1] is None
        cmds.redo();assert read()[1]['layers'][0]['id']==layer
        right=next(i for i,path in enumerate(ctx['influences']) if path.fullPathName().endswith('right_JNT'))
        right_id=ctx['ids'][right]
        new_joint=cmds.createNode('joint',name=demo['namespace']+':added_JNT',parent=demo['joints'][0])
        new_id=helper.joint_id(new_joint)
        settings=dict(method='axis',axis='+X')
        call('assign',layer=layer,joints=[right_id],whole=True,settings=settings)
        ctx,state=read();assert state.get('reference') and state['layers'][0]['generated']
        assert state['layers'][0]['joints']==[right_id]
        assert new_id in state['reference']['joints'] and new_id not in ctx['ids'],'Unbound descendants were not frozen with the mesh'
        reference_key=state['reference']['key'];undo_name=cmds.undoInfo(query=True,undoName=True)
        count=helper.sibling('layer_skin_assignment').CACHE.vertex_tests
        call('assign',layer=layer,whole=True,settings=settings)
        assert helper.sibling('layer_skin_assignment').CACHE.vertex_tests==count
        assert cmds.undoInfo(query=True,undoName=True)==undo_name,'Repeated identical assignment created an Undo entry'
        # The global MEL wrappers must return real scalar values, not None.
        session.start(mesh,layer,joint=right_id,mode='mask')
        report=session.paint_report()
        assert report['active_context']==api.paint_context and report['object_selection_mode'],report
        settings_report=report['context_settings']
        assert settings_report['whichTool']=='userPaint' and settings_report['stampProfile']=='gaussian',report
        assert settings_report['outline'] and settings_report['colorfeedback'] and settings_report['disablelighting'],report
        assert ctx['shape'] in report['selected_surfaces'],report
        assert mel.eval('rtkLSSurface041('+json.dumps(ctx['shape'])+')')==ctx['shape'],report
        assert mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')=='-id 1'
        assert abs(mel.eval('rtkLSGet041(1,0)')-1.)<1e-8
        mel.eval('rtkLSSet041(1,0,0.25)');mel.eval('rtkLSFinish041(1)')
        assert abs(read()[1]['layers'][0]['mask']['0']-.25)<1e-8
        saved_mask=helper.core.encode(read()[1])
        for _ in range(2):
            session.start(mesh,layer,joint=right_id,mode='weights')
            session.start(mesh,layer,mode='mask',readonly=True)
            assert session.paint_report()['view_ready'] and not session.paint_report()['configuring_view']
            assert mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')=='-id 1'
            assert session.stroke is None,'Viewing a mask opened an unfinished authoring stroke'
            assert abs(mel.eval('rtkLSGet041(1,0)')-.25)<1e-8
            assert helper.core.encode(read()[1])==saved_mask,'View switching changed saved mask data'
        session.stop();cmds.undo();assert '0' not in read()[1]['layers'][0]['mask']
        # One-joint paint is a distribution plus coverage; below stays live.
        session.start(mesh,layer,joint=right_id,mode='weights')
        # Exercise a rejected stroke followed by another gesture without
        # reactivating the brush. This changes only this demo's own skin.
        before_rejected=helper.core.encode(read()[1])
        cmds.setAttr(demo['skin']+'.maintainMaxInfluences',True)
        mel.eval('rtkLSBefore041()')
        mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')
        mel.eval('rtkLSSet041(1,0,0.4)');mel.eval('rtkLSFinish041(1)')
        assert session.last_stroke['status']=='rejected',session.paint_report()
        assert helper.core.encode(read()[1])==before_rejected,'Rejected stroke changed saved layer data'
        cmds.setAttr(demo['skin']+'.maintainMaxInfluences',False)
        mel.eval('rtkLSBefore041()');mel.eval('rtkLSSet041(1,0,0.4)')
        # A repeated surface request must not erase pending values.
        mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')
        assert abs(mel.eval('rtkLSGet041(1,0)')-.4)<1e-6
        mel.eval('rtkLSAfter041()');mel.eval('rtkLSFinish041(1)')
        assert session.last_stroke['status']=='saved' and session.last_stroke['layer_values_verified'],session.paint_report()
        assert session.paint_report()['last_callback_error'] is None
        saved_paint=helper.core.encode(read()[1]);save_receipt=dict(session.last_stroke)
        left_id=helper.joint_id(demo['joints'][0])
        for _ in range(2):
            session.start(mesh,layer,joint=left_id,mode='weights')
            session.start(mesh,layer,mode='mask',readonly=True)
            session.start(mesh,layer,joint=right_id,mode='weights')
            assert abs(mel.eval('rtkLSGet041(1,0)')-.4)<1e-6
            assert session.last_stroke==save_receipt,'View switching erased the last save result'
            assert helper.core.encode(read()[1])==saved_paint,'View switching changed saved weight data'
        session.stop()
        painted=read()[1]['layers'][0]['samples']['0'];assert abs(painted['coverage']-.4)<1e-6
        call('assign',layer=layer,whole=True,settings=dict(settings,falloff=2.))
        assert read()[1]['layers'][0]['samples']['0']==painted,'Rebuild erased paint'
        assert read()[1]['reference']['key']==reference_key
        # Choosing/activating an unbound joint is read-only; the released stroke
        # binds at zero and records membership/weight in the same Undo step.
        old_ctx,old_state=read();old_weights=old_ctx['weights'][:]
        session.start(mesh,layer,joint=new_id,joint_path=new_joint,mode='weights')
        assert new_id not in read()[0]['ids']
        mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')
        mel.eval('rtkLSSet041(1,1,0.75)');mel.eval('rtkLSFinish041(1)');session.stop()
        added_ctx,added_state=read();column=added_ctx['ids'].index(new_id)
        assert abs(added_ctx['weights'][len(added_ctx['ids'])+column]-.75)<1e-6
        assert all(abs(added_ctx['weights'][v*len(added_ctx['ids'])+column])<1e-8 for v in range(added_ctx['count']) if v!=1)
        assert new_id in added_state['layers'][0]['joints']
        assert added_state['layers'][0]['samples']['0']['coverage']==painted['coverage']
        cmds.undo();undone,_=read();assert new_id not in undone['ids'] and helper.same(undone['weights'],old_weights,2e-6)
        assert cmds.objExists(new_joint),'Undo deleted the chosen scene joint'
        cmds.redo();assert new_id in read()[0]['ids']
        session.edit_joints(mesh,layer,[new_joint],'assign',dict(whole=True,settings=dict(method='point',radius=10.)))
        assert read()[1]['reference']['key']==reference_key,'Assignment silently recaptured the reference'
        # Final skin inspection must read actual native values and ignore edits.
        ctx,state=read();before_view=list(ctx['weights']);raw_before=helper.core.encode(state)
        column=ctx['ids'].index(right_id);expected=ctx['weights'][column::len(ctx['ids'])]
        session.start(mesh,layer,joint=right_id,mode='skin',readonly=True)
        assert helper.same(session.values,expected,2e-6)
        mel.eval('rtkLSInit041('+json.dumps(ctx['shape'])+')')
        mel.eval('rtkLSSet041(1,0,0.123)');mel.eval('rtkLSFinish041(1)');session.stop()
        assert helper.same(read()[0]['weights'],before_view,2e-6) and helper.core.encode(read()[1])==raw_before
        # Animation does not recalculate authoring data or generated assignments.
        raw=cmds.getAttr(helper.metadata(read()[0])[0]+'.rtkLayerSkinData')
        cmds.setAttr(demo['joints'][1]+'.rotateY',25);assert cmds.getAttr(helper.metadata(read()[0])[0]+'.rtkLayerSkinData')==raw
        call('bake');assert read()[1] is None
        print('Layer Skin native authoring: PASS (userPaint/Gaussian setup, read-only actual skin weights, auto Base, selected-joint assignment, frozen unbound descendants, direct first-stroke binding/membership with Undo/Redo, cached assignment and MEL scalar painting). Cursor feedback, mouse gestures and viewport shading still require manual verification.')
    finally:
        session.close();helper.clear_cache();cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        remaining=[node for node in selection if cmds.objExists(node)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)



def run_capture_recovery():
    """Native data test with deliberately omitted begin/end paint callbacks."""
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo first.')
    import maya.mel as mel
    helper=_helpers();session=helper.editor_api().make_session()
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    demo=make_demo();mesh=demo['mesh']
    def read():
        ctx=helper.context(mesh);return ctx,helper.metadata(ctx)[1]
    try:
        cmds.rtkLayerSkin(action='add',data=json.dumps(dict(target=mesh,name='Capture recovery')))
        ctx,state=read();layer=state['layers'][0]['id'];left,right=[helper.joint_id(path) for path in demo['joints']]
        session.start(mesh,layer,joint=right,mode='weights')
        # No Init/Before/Finish/After: this reproduces the lost-pending-data path.
        mel.eval('rtkLSSet041(1,0,0.65)')
        assert session.stroke and session.stroke['values'],session.paint_report()
        session.start(mesh,layer,joint=left,mode='weights')
        assert session.last_stroke['status']=='saved' and session.last_stroke['commit_reason']=='view_change',session.paint_report()
        ctx,state=read();column=ctx['ids'].index(right)
        assert abs(ctx['weights'][column]-.65)<2e-6,'Switch did not save the native skin weight'
        session.start(mesh,layer,joint=right,mode='weights')
        assert abs(session.get_value(1,0)-.65)<2e-6,'Returning to the painted joint loaded zero'
        session.start(mesh,layer,mode='mask')
        mel.eval('rtkLSSet041(1,1,0.25)')
        session.start(mesh,layer,joint=right,mode='weights')
        assert abs(read()[1]['layers'][0]['mask']['1']-.25)<2e-6
        session.start(mesh,layer,mode='mask',readonly=True)
        assert abs(session.get_value(1,1)-.25)<2e-6
        assert session.paint_report()['callback_counts']['accepted_sample']>=2
        session.stop();cmds.undo();assert '1' not in read()[1]['layers'][0]['mask']
        cmds.redo();assert abs(read()[1]['layers'][0]['mask']['1']-.25)<2e-6
        print('Layer Skin native capture recovery: PASS (omitted stroke callbacks, weight/mask save on view change, native readback and Undo/Redo). Actual brush delivery and Qt release fallback still need GUI testing.')
    finally:
        session.close();helper.clear_cache();cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        remaining=[node for node in selection if cmds.objExists(node)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)


def run_ui_lifecycle():
    """Explicit Maya GUI test: creates its own demo and opens/closes its UI three times."""
    helper=_helpers()
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    app=QtWidgets.QApplication.instance()
    if any(widget.objectName()==helper.WINDOW and widget.isVisible() for widget in app.allWidgets()):
        raise RuntimeError('Close the existing Layer Skin window before this UI lifecycle test.')
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    demo=make_demo();window=None
    child=cmds.createNode('joint',name=demo['namespace']+':treeChild_JNT',parent=demo['joints'][0])
    cmds.createNode('joint',name=demo['namespace']+':treeTip_JNT',parent=child)
    outliner_colors={joint:(cmds.getAttr(joint+'.useOutlinerColor'),cmds.getAttr(joint+'.outlinerColor')) for joint in demo['joints']}
    try:
        for cycle in range(3):
            cmds.select(demo['mesh'],replace=True);window=helper.show_ui();window.follow_selection()
            assert window.ctx and window.layers.order()[-1]=='__base__'
            assert len(window.session.callbacks)==6+int(hasattr(helper.om.MSceneMessage,'kMayaExiting'))
            assert window.browser and window.browser.widget,'Joint hierarchy widget was not created'
            tree=window.browser.widget
            assert tree.topLevelItemCount()==1 and tree.topLevelItem(0).childCount()==1,'Scene joint hierarchy was not populated'
            assert tree.topLevelItem(0).child(0).childCount()==1,'The third joint is not nested under the second'
            try:
                from PySide6 import QtCore
            except ImportError:
                from PySide2 import QtCore
            assert window.dock_layout.dockWidgetArea(window.joint_dock)==QtCore.Qt.RightDockWidgetArea
            assert not window.findChildren(QtWidgets.QListWidget),'Duplicate influence list is still present'
            assert window.browser.styling.delegates,'Joint weight-status styling was not installed'
            if cycle==0:
                assert window.run('add')
                assert not window.browser.weighted,'Empty layer has nonzero weight styling'
                assert window.run('mask',dict(whole=True,value=.25))
                window.paint_mode.setCurrentIndex(1);window.paint()
                assert abs(window.session.get_value(1,0)-.25)<1e-8
                cmds.undo();window.follow_selection()
                assert window.session.active and window.session.mode=='mask'
                assert abs(window.session.get_value(1,0)-1.)<1e-8,'Mask view stayed stale after Undo'
                cmds.redo();window.follow_selection()
                assert abs(window.session.get_value(1,0)-.25)<1e-8,'Mask view stayed stale after Redo'
                window.stop_paint();ctx=helper.context(demo['mesh'])
                right=next(path.fullPathName() for path in ctx['influences'] if path.fullPathName().endswith('right_JNT'))
                window.choose_joint(right)
                window.browser_selected()
                identity=helper.joint_id(right)
                assert window.active_joint()==identity
                window.show_skin.setChecked(True)
                assert window.session.mode=='skin' and window.session.readonly
                window.stop_paint();assert not window.show_skin.isChecked()
                assert window.run('paint',dict(mode='weights',joint=identity,values={'0':1.}))
                assert window.browser.weighted=={identity}
                cmds.undo();window.follow_selection();assert not window.browser.weighted
                for joint,colors in outliner_colors.items():
                    assert (cmds.getAttr(joint+'.useOutlinerColor'),cmds.getAttr(joint+'.outlinerColor'))==colors,'UI changed global joint Outliner colors'
            browser=window.browser;window.close()
            assert window.session.callbacks==[]
            assert browser.closed and browser.widget is None,'Joint browser resources leaked after close'
        print('Layer Skin native UI lifecycle: PASS (visible nested joint tree, right dock, per-layer weight status, unchanged scene Outliner colors, mask-view Undo/Redo, callback removal and repeated close/reopen). Manually check real brush gestures and Maya appearance.')
    finally:
        if window and not window._closed:window.close()
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        remaining=[node for node in selection if cmds.objExists(node)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)
