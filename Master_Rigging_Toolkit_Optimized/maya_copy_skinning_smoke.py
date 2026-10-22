"""Native Maya Copy Skinning test. Does not open, save or replace the current scene."""
import importlib.util
import json
import os
import uuid
import maya.cmds as cmds
import maya.api.OpenMaya as om


def load():
    path=os.path.join(os.path.dirname(__file__),'copy_skinning_plugin.py')
    paths=[cmds.pluginInfo(p,query=True,path=True) for p in (cmds.pluginInfo(query=True,listPlugins=True) or [])]
    if not any(os.path.realpath(p)==os.path.realpath(path) for p in paths):cmds.loadPlugin(path,quiet=True)
    if cmds.pluginInfo(path,query=True,version=True)!='0.4.3':raise RuntimeError('Save and restart Maya with Copy Skinning 0.4.3 before running this test.')
    spec=importlib.util.spec_from_file_location('_copy_skin_native_helpers',path)
    api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api);return api


def make_demo():
    api=load();prefix='copySkinDemo_'+uuid.uuid4().hex[:8];namespace=cmds.namespaceInfo(currentNamespace=True)
    cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
    try:
        root=cmds.createNode('transform',name=prefix+':DEMO');joints=[]
        for name,x in (('A_JNT',0),('B_JNT',2)):
            j=cmds.createNode('joint',name=prefix+':'+name,parent=root);cmds.setAttr(j+'.translateX',x);joints.append(j)
        meshes=[]
        for name,points in (('source',[(0,0,0),(2,0,0),(0,2,0)]),('target',[(.5,.5,1),(0,0,1),(.8,.2,1)])):
            mesh=cmds.polyCreateFacet(name=prefix+':'+name,point=points,constructionHistory=False)[0]
            mesh=cmds.parent(mesh,root)[0];meshes.append(mesh)
            skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)[0]
            cmds.setAttr(skin+'.maintainMaxInfluences',False)
        source,target=(api.context(n) for n in meshes)
        for joint in joints:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        def physical(ctx,joint):
            identity=om.MFnDependencyNode(api.object_(joint)).uuid().asString()
            return next(i for i,record in enumerate(ctx['influences']) if record['uuid']==identity)
        for ctx,rows in ((source,[(1,0),(0,1),(0,1)]),(target,[(0,1)]*3)):
            a,b=(physical(ctx,j) for j in joints);values=[]
            for row in rows:
                ordered=[0.,0.];ordered[a],ordered[b]=row;values.extend(ordered)
            ctx['fn'].setWeights(ctx['dag'],api.components(range(3)),om.MIntArray([0,1]),om.MDoubleArray(values),False)
        source['fn'].setBlendWeights(source['dag'],api.components(range(3)),om.MDoubleArray([.2,.6,1.]))
        target['fn'].setBlendWeights(target['dag'],api.components(range(3)),om.MDoubleArray([0,0,0]))
        cmds.select(meshes,replace=True)
        return {'namespace':prefix,'root':root,'source':meshes[0],'target':meshes[1],'joints':joints}
    finally:cmds.namespace(setNamespace=namespace)


def run():
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo first.')
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    linear=cmds.currentUnit(query=True,linear=True)
    cmds.currentUnit(linear='cm');demo=make_demo()
    def data(method='surface',**kw):return dict(source=demo['source'],target=demo['target'],method=method,geometry='base',**kw)
    def weights():return api.context(demo['target'])['weights']
    def execute(values):return json.loads(cmds.rtkCopySkin(data=json.dumps(values)))
    def close(a,b):return api.same(a,b,2e-5)
    try:
        source=api.context(demo['source']);target=api.context(demo['target']);before=weights()
        assert api.bind_target(demo['source'],demo['target'])==target['skin']
        assert weights()==before,'Preparing an already skinned target must keep existing weights'
        a_id=om.MFnDependencyNode(api.object_(demo['joints'][0])).uuid().asString()
        a_column=next(i for i,j in enumerate(target['influences']) if j['uuid']==a_id)
        preview=api.plan(data(copy_dq=True));assert weights()==before,'Preview must not write weights'
        assert preview['vertices']==[0,1,2]
        result=execute(data(copy_dq=True));assert result['changed_vertices']==3
        after=weights();assert close(after[:2],[.5,.5]),after
        ctx=api.context(demo['target']);dq=ctx['fn'].getBlendWeights(ctx['dag'],api.components([0]))
        assert abs(dq[0]-.5)<2e-5
        cmds.undo();assert close(weights(),before),'One Undo must restore all weights'
        cmds.redo();assert close(weights(),after)
        cmds.undo()
        # Vertex IDs ignore spatial differences, including target z offset.
        execute(data(method='id'))
        mapping=api.core.influence_mapping(source['influences'],target['influences'])
        expected=[]
        for v in range(3):expected.extend(api.core.interpolate(source['weights'],2,(v,v,v),(1,0,0),mapping,2))
        assert close(weights(),expected)
        cmds.undo();assert close(weights(),before)
        # Source and target masks multiply to alpha .25 at target vertex 0.
        api.mask_action(demo['source'],'source','white')
        cmds.select(demo['source']+'.vtx[*]',replace=True);api.mask_action(demo['source'],'source','selected',.5)
        api.mask_action(demo['target'],'target','black')
        cmds.select(demo['target']+'.vtx[0]',replace=True);api.mask_action(demo['target'],'target','selected',.5)
        values=data(method='region',source_mask=True,target_mask=True)
        result=execute(values);assert result['changed_vertices']==1
        assert abs(weights()[a_column]-.125)<2e-5 and abs(weights()[1-a_column]-.875)<2e-5
        assert close(weights()[2:],before[2:])
        cmds.undo();assert close(weights(),before)
        # Captured faces restrict the source triangle; target capture limits IDs.
        cmds.select(demo['source']+'.f[0]',replace=True);source_region=api.capture_region(demo['source'],True)
        cmds.select(demo['target']+'.vtx[1]',replace=True);target_region=api.capture_region(demo['target'])
        result=execute(data(method='region',source_region=source_region,target_region=target_region))
        assert result['changed_ids']==[1];cmds.undo();assert close(weights(),before)
        # Max distance honors current scene units (0.005 m = 0.5 cm < 1cm gap).
        cmds.currentUnit(linear='m')
        result=api.plan(data(max_distance=.005));assert not result['vertices']
        cmds.currentUnit(linear='cm')
        # Base sampling remains undeformed while current sampling follows joints.
        ctx=api.context(demo['source']);base_points=api.sample_geometry(ctx,'base')[0]
        cmds.setAttr(demo['joints'][1]+'.translateY',2)
        ctx=api.context(demo['source']);assert api.sample_geometry(ctx,'base')[0]==base_points
        assert api.sample_geometry(ctx,'current')[0]!=base_points
        # Nonuniform object transforms are handled in world coordinates.
        cmds.setAttr(demo['root']+'.scale',2,.5,1,type='double3')
        assert api.plan(data())['summary']['eligible_vertices']==3
        print('PASS: preview, barycentric surface interpolation, vertex IDs, source/target masks, component restrictions, current/base geometry, DQ, world transforms, distance units and native Undo/Redo.')
    finally:
        cmds.setToolTo('selectSuperContext');cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);cmds.currentUnit(linear=linear)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_mapping():
    """Native independent-skeleton matching, bind positions, manual mapping and reuse."""
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo first.')
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    unit=cmds.currentUnit(query=True,linear=True);cmds.currentUnit(linear='cm');demo=make_demo()
    try:
        target=cmds.polyCreateFacet(name=demo['namespace']+':mappedTarget',point=[(.5,.5,1),(0,0,1),(.8,.2,1)],constructionHistory=False)[0]
        target=cmds.parent(target,demo['root'])[0];other=[]
        for name,x in (('A_A_JNT',0),('A_B_JNT',2)):
            joint=cmds.createNode('joint',name=demo['namespace']+':'+name,parent=demo['root']);cmds.setAttr(joint+'.translateX',x);other.append(joint)
        skin=cmds.skinCluster(other,target,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        for joint in other:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        source=api.context(demo['source']);ctx=api.context(target);before=ctx['weights'][:]
        values={'source':demo['source'],'target':target,'method':'surface','geometry':'base','joint_tolerance':.01}
        report=api.mapping_report(values);assert report['complete'],report['errors']
        assert all('distance' in row['method'].lower() for row in report['rows'])
        assert api.bind_target(demo['source'],target)==skin
        assert api.context(target)['weights']==before
        # Joint animation changes current matches but leaves bind/rest mapping stable.
        cmds.setAttr(demo['joints'][1]+'.translateY',1)
        bind=api.mapping_report(dict(values,match_name=False,joint_space='bind'));assert bind['complete']
        current=api.mapping_report(dict(values,match_name=False,joint_space='current'));assert not current['complete']
        source_ids=[r['uuid'] for r in source['influences']]
        other_ids=[om.MFnDependencyNode(api.object_(joint)).uuid().asString() for joint in other]
        source_a=om.MFnDependencyNode(api.object_(demo['joints'][0])).uuid().asString()
        source_b=next(identity for identity in source_ids if identity!=source_a)
        manual={source_a:other_ids[1],source_b:other_ids[0]}
        result=json.loads(cmds.rtkCopySkin(data=json.dumps(dict(values,manual_mapping=manual))))
        assert all(row['method']=='Manual' for row in result['mapping_details'])
        after=api.context(target);b_column=next(i for i,r in enumerate(after['influences']) if r['uuid']==other_ids[1])
        assert abs(after['weights'][after['width']+b_column]-1)<2e-5
        cmds.undo();assert api.same(api.context(target)['weights'],before,2e-5)
        cmds.redo();assert api.same(api.context(target)['weights'],after['weights'],2e-5)
        print('PASS: existing skin reuse, independent skeletons, name+distance matching, bind/current positions, manual UUID mapping, mapped weight columns and native Undo/Redo.')
    finally:
        cmds.setToolTo('selectSuperContext');cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);cmds.currentUnit(linear=unit)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)



def run_progress():
    """Native window cleanup on success/failure/cancel; does not simulate key input."""
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or [];demo=make_demo()
    data=dict(source=demo['source'],target=demo['target'],method='surface',geometry='base')
    original=api.PlanProgress.check
    def assert_released():
        assert not api._active_plan,'Operation guard was left active'
        owned=bool(cmds.progressWindow(title='Copy Skinning cleanup probe',progress=0))
        try:assert owned,'Previous progress window was not released'
        finally:
            if owned:cmds.progressWindow(endProgress=True)
    try:
        before=api.context(demo['target'])['weights']
        api.plan(data,progress=True);assert_released()
        for stage in ('Preparing source','Building source','Sampling target','Checking target'):
            def cancel(monitor):
                original(monitor)
                if monitor.status.startswith(stage):raise RuntimeError('Test cancellation')
            api.PlanProgress.check=cancel
            try:
                api.plan(data,progress=True)
                raise AssertionError('Expected cancellation')
            except RuntimeError as exc:
                assert str(exc)=='Test cancellation',str(exc)
            finally:api.PlanProgress.check=original
            assert_released();assert api.context(demo['target'])['weights']==before
        try:
            api.plan(dict(data,source='__copy_skin_missing_'+uuid.uuid4().hex),progress=True)
            raise AssertionError('Expected mesh read failure')
        except ValueError:pass
        assert_released();assert api.context(demo['target'])['weights']==before
        print('Copy Skinning native progress cleanup: PASS. Test real Escape input manually on a larger mesh.')
    finally:
        api.PlanProgress.check=original
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        remaining=[n for n in selection if cmds.objExists(n)]
        cmds.select(remaining,replace=True) if remaining else cmds.select(clear=True)


def run_cache():
    """Native pre-skin data, shared command cache and deformation invalidation."""
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=om.MGlobal.getActiveSelectionList();demo=make_demo()
    data=dict(source=demo['source'],target=demo['target'],method='surface',geometry='base')
    try:
        api.clear_cache()
        source=api.load_mesh(demo['source'],source=True);api.load_mesh(demo['target'])
        assert '.input[' in source['input_geometry'],source
        assert api.cache_stats()['surface_builds']==1
        first=api.plan(data,progress=True);assert first['summary']['surface_cache_reused']
        queries=api.cache_stats()['nearest_queries'];assert queries>0
        before=api.context(demo['target'])['weights']
        summary=json.loads(cmds.rtkCopySkin(data=json.dumps(data)))
        assert summary['correspondence_cache_reused'],'Registered command must share the panel helper cache'
        assert api.cache_stats()['nearest_queries']==queries
        cmds.undo();assert api.same(api.context(demo['target'])['weights'],before)
        api.plan(data);assert api.cache_stats()['nearest_queries']==queries
        # Weight painting with unchanged geometry must use fresh weights and old correspondence.
        ctx=api.context(demo['source']);values=[1.,0.]*3
        ctx['fn'].setWeights(ctx['dag'],api.components(range(3)),om.MIntArray([0,1]),om.MDoubleArray(values),False)
        changed=api.plan(data);assert api.cache_stats()['nearest_queries']==queries
        assert changed['after']!=first['after'],'Source weights must never come from geometry cache'
        # Pose changes affect Current; Pre-skin correspondence stays reusable.
        api.plan(dict(data,geometry='current'));current_queries=api.cache_stats()['nearest_queries']
        cmds.setAttr(demo['joints'][0]+'.translateZ',1)
        cmds.setAttr(demo['joints'][1]+'.translateZ',1)
        api.plan(data);assert api.cache_stats()['nearest_queries']==current_queries
        api.plan(dict(data,geometry='current'));assert api.cache_stats()['nearest_queries']>current_queries
        # An animated blendShape BEFORE the skin must be included in pre-skin input.
        cmds.namespace(setNamespace=':')
        mesh=cmds.polyCreateFacet(name=demo['namespace']+':upstreamMesh',point=[(0,0,0),(2,0,0),(0,2,0)],constructionHistory=False)[0]
        mesh=cmds.parent(mesh,demo['root'])[0];target=cmds.duplicate(mesh,name=demo['namespace']+':blendTarget')[0]
        cmds.move(0,0,1,target+'.vtx[0]',relative=True,objectSpace=True)
        blend=cmds.blendShape(target,mesh,name=demo['namespace']+':beforeSkinBlend')[0]
        skin=cmds.skinCluster(demo['joints'],mesh,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False);cmds.setAttr(blend+'.weight[0]',0)
        ctx=api.context(mesh);base0=api.sample_geometry(ctx,'base')[0]
        cmds.setAttr(blend+'.weight[0]',1)
        # Reuse the context deliberately: sample_geometry must re-evaluate inputGeometry.
        base1=api.sample_geometry(ctx,'base')[0]
        assert abs(base1[0][2]-base0[0][2])>1e-6,'Pre-skin data must include the upstream blendShape'
        assert base0!=base1,'Pre-skin cache must invalidate on upstream edits'
        assert api.cache_stats()['estimated_bytes']<=api.cache_service().max_bytes
        api.clear_cache();assert api.cache_stats()['items']==0
        print('Copy Skinning native cache checks: PASS (automatic skin input, upstream blendShape, shared cache, painted weights, Undo and pose invalidation).')
    finally:
        api.clear_cache();cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);om.MGlobal.setActiveSelectionList(selection)


def run_actions():
    """Native lightweight preview, bulk component selection and sparse plug guards."""
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=om.MGlobal.getActiveSelectionList();demo=make_demo()
    data=dict(source=demo['source'],target=demo['target'],method='surface',geometry='base')
    try:
        ctx=api.context(demo['target']);before=ctx['weights'][:];api.clear_cache()
        preview=api.preview_transfer(data);assert preview['write_preflight']=='deferred until Copy'
        assert api.same(api.context(demo['target'])['weights'],before)
        selected=api.select_preview_vertices(data);assert selected['preview_cache_reused']
        assert api.capture_region(demo['target'])['vertices']==selected['changed_ids']
        assert api.same(api.context(demo['target'])['weights'],before)
        # Use a nonzero column so a connected value does not create zero-sum rows.
        column=next(i for i,value in enumerate(before[:ctx['width']]) if value>0)
        path=ctx['fn'].influenceObjects()[column]
        try:logical=ctx['fn'].indexForInfluenceObject(path)
        except TypeError:logical=ctx['fn'].indexForInfluenceObject(path.node())
        plug=ctx['skin']+'.weightList[0].weights[{}]'.format(logical)
        cmds.setAttr(plug,lock=True)
        try:
            assert api.preview_transfer(data)['preview_cache_reused'],'Read-only preview may inspect a locked target'
            try:api.plan(data);raise AssertionError('Copy preflight must reject the locked weight')
            except ValueError as exc:assert 'locked' in str(exc),str(exc)
        finally:cmds.setAttr(plug,lock=False)
        driver=cmds.createNode('addDoubleLinear',name=demo['namespace']+':guardDriver')
        cmds.setAttr(driver+'.input1',before[column]);cmds.connectAttr(driver+'.output',plug)
        try:
            try:api.plan(data);raise AssertionError('Copy preflight must reject the incoming driver')
            except ValueError as exc:assert 'driver' in str(exc),str(exc)
        finally:cmds.disconnectAttr(driver+'.output',plug)
        try:
            api.preview_transfer(dict(data,max_seconds=1e-12))
            raise AssertionError('Expected calculation time limit')
        except RuntimeError as exc:assert 'time limit' in str(exc),str(exc)
        assert api.same(api.context(demo['target'])['weights'],before)
        result=json.loads(cmds.rtkCopySkin(data=json.dumps(data)));assert result['changed_vertices']==3
        cmds.undo();assert api.same(api.context(demo['target'])['weights'],before)
        owned=bool(cmds.progressWindow(title='Copy Skinning action cleanup probe',progress=0))
        try:assert owned,'Action left the progress window reserved'
        finally:
            if owned:cmds.progressWindow(endProgress=True)
        print('Copy Skinning native action checks: PASS (read-only reuse, component selection, sparse locks/drivers, timeout, Copy/Undo and progress cleanup).')
    finally:
        api.clear_cache();cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);om.MGlobal.setActiveSelectionList(selection)


def run_unskinned():
    """Native bare/history-only source rejection, cleanup and a valid load retry."""
    api=load();namespace=cmds.namespaceInfo(currentNamespace=True);selection=om.MGlobal.getActiveSelectionList()
    prefix='copySkinUnskinned_'+uuid.uuid4().hex[:8];demo=None;api.clear_cache()
    cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
    try:
        bare=cmds.polyCube(name=prefix+':bareSource',constructionHistory=False)[0]
        history=cmds.polyCube(name=prefix+':historySource',constructionHistory=True)[0]
        for mesh in (bare,history,bare):
            try:
                api.load_mesh(mesh,source=True)
                raise AssertionError('Unskinned source was accepted: '+mesh)
            except ValueError as exc:assert 'no skinCluster' in str(exc),str(exc)
            assert not api._active_plan,'Load left the operation guard active'
            assert api.cache_stats()['items']==0,'Invalid source populated the cache'
            owned=bool(cmds.progressWindow(title='Unskinned load cleanup probe',progress=0))
            try:assert owned,'Invalid Load left progress reserved'
            finally:
                if owned:cmds.progressWindow(endProgress=True)
        assert not (cmds.ls(cmds.listHistory(bare) or [],type='skinCluster') or []),'Load must not bind the source'
        demo=make_demo();info=api.load_mesh(demo['source'],source=True)
        assert info['influences']==2 and info['vertices']==3,'Valid skinned Load failed after invalid loads'
        print('Copy Skinning native unskinned-source checks: PASS (bare source, construction history, repeated failure cleanup, no binding and valid retry).')
    finally:
        api.clear_cache();cmds.namespace(setNamespace=':')
        for name in (prefix,demo['namespace'] if demo else None):
            if name and cmds.namespace(exists=name):cmds.namespace(removeNamespace=name,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);om.MGlobal.setActiveSelectionList(selection)


def run_tasks():
    """Native shared task state, cancellation, progress diagnostics and Copy Undo."""
    api=load();service=api.task_service()
    if service.active or api.native_progress_info():raise RuntimeError('Finish the current task/progress before running the task smoke test.')
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=om.MGlobal.getActiveSelectionList();demo=make_demo()
    try:
        data=dict(source=demo['source'],target=demo['target'],method='surface',geometry='base')
        before=api.context(demo['target'])['weights'][:]
        try:
            with api.planning(True,label='Native task cancellation probe') as monitor:
                monitor.stage('Before weight calculation',10);identity=service.active['id']
                api.stop_task(identity,force=True);monitor.check();raise AssertionError('Cancellation was not observed')
        except api.task_module().TaskCancelled:pass
        assert service.active is None and service.history[0]['state']=='Cancelled'
        assert api.same(before,api.context(demo['target'])['weights'])
        owned=bool(cmds.progressWindow(title='Task recovery smoke window',status='Idle test window',progress=0))
        if not owned:raise AssertionError('Could not create recovery test window')
        try:
            info=api.task_report()['maya_progress'];assert info and 'recovery smoke' in info['title']
            message=api.stop_task('maya-progress',force=True,expected_progress=info);assert 'does not terminate' in message
        finally:cmds.progressWindow(endProgress=True)
        summary=json.loads(cmds.rtkCopySkin(data=json.dumps(data)));assert summary['changed_vertices']==3
        assert service.history[0]['name']=='Copy skinning' and service.history[0]['state']=='Completed'
        cmds.undo();assert api.same(before,api.context(demo['target'])['weights'])
        assert service.active is None
        print('Copy Skinning native task checks: PASS (shared command/helper records, cancel request, progress reset and Copy Undo).')
    finally:
        api.clear_cache();cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=demo['namespace']):cmds.namespace(removeNamespace=demo['namespace'],deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);om.MGlobal.setActiveSelectionList(selection)
