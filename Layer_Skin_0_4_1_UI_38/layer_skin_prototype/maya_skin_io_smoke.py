"""Native Maya smoke tests; open Layer Skin UI 20, then run run(keep=True).

Creates only its own namespace and temporary backup file. Does not clear the
scene, unload a plug-in, delete user rigs or reset Undo. Not a mouse-brush test.
"""
import os
import tempfile
import uuid


def run(window=None,keep=True):
    import maya.cmds as cmds
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    if window is None:
        app=QtWidgets.QApplication.instance()
        windows=[w for w in app.topLevelWidgets() if w.objectName()=='rtkLayerSkinPrototypeWindow' and w.isVisible() and hasattr(w,'utilities')]
        if len(windows)!=1:raise RuntimeError('Open one Layer Skin UI 9 window first.')
        window=windows[0]
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Maya Undo for the smoke test.')
    if not window.stop_paint():raise RuntimeError('Save or resolve the current paint stroke before testing.')
    api=window.api;service=window.utilities.backend;io=window.utilities.io
    selection=api.om.MGlobal.getActiveSelectionList();old_namespace=cmds.namespaceInfo(currentNamespace=True)
    namespace='layerSkinIO_'+uuid.uuid4().hex[:8];cmds.namespace(setNamespace=':');cmds.namespace(add=namespace)
    prefix=':'+namespace+':';report={}
    def component(count):
        fn=api.om.MFnSingleIndexedComponent();value=fn.create(api.om.MFn.kMeshVertComponent);fn.addElements(range(count));return value
    try:
        root=cmds.createNode('transform',name=prefix+'Source')
        joints=[cmds.createNode('joint',name=prefix+name,parent=root) for name in ('jointA','jointB')]
        cmds.setAttr(joints[0]+'.translateX',-1.);cmds.setAttr(joints[1]+'.translateX',1.)
        mesh=cmds.polyPlane(name=prefix+'sourceMesh',width=2,height=2,subdivisionsX=4,subdivisionsY=4,constructionHistory=False)[0]
        mesh=cmds.parent(mesh,root)[0];skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False);cmds.setAttr(skin+'.skinningMethod',2)
        ctx=api.context(mesh);comp=component(ctx['count']);amounts=[v/(ctx['count']-1) for v in range(ctx['count'])]
        weights=[w for value in amounts for w in (1.-value,value)]
        ctx['fn'].setWeights(ctx['dag'],comp,api.om.MIntArray([0,1]),api.om.MDoubleArray(weights),False)
        ctx['fn'].setBlendWeights(ctx['dag'],comp,api.om.MDoubleArray(amounts))
        with tempfile.TemporaryDirectory(prefix='layer_skin_io_') as folder:
            path=os.path.join(folder,'native.rtkskin');report['export']=service.export(mesh,path)
            snapshot=io.read(path);assert api.same(snapshot['weights'],weights,2e-6)
            assert api.same(snapshot['dq'],amounts,2e-6)
            ctx['fn'].setWeights(ctx['dag'],comp,api.om.MIntArray([0,1]),api.om.MDoubleArray([1.,0.]*ctx['count']),False)
            ctx['fn'].setBlendWeights(ctx['dag'],comp,api.om.MDoubleArray([0.]*ctx['count']));cmds.setAttr(skin+'.skinningMethod',0)
            before=api.context(mesh)['weights'];plan=service.preview(snapshot,mesh,root=root,name='Native file import')
            service.commit(plan);actual=api.context(mesh)
            assert api.same(actual['weights'],snapshot['weights'],2e-6)
            assert api.same(actual['fn'].getBlendWeights(actual['dag'],comp),snapshot['dq'],2e-6)
            assert cmds.getAttr(skin+'.skinningMethod')==2
            assert len(api.metadata(actual)[1]['layers'])==1
            cmds.undo();actual=api.context(mesh)
            assert api.same(actual['weights'],before,2e-6) and api.metadata(actual)[0] is None
            assert cmds.getAttr(skin+'.skinningMethod')==0
            assert api.same(actual['fn'].getBlendWeights(actual['dag'],comp),[0.]*actual['count'],2e-6)
            cmds.redo();assert api.same(api.context(mesh)['weights'],snapshot['weights'],2e-6)
            report['vertex_id_undo_redo']='passed'
            destination=cmds.createNode('transform',name=prefix+'Destination')
            dest_joints=[cmds.createNode('joint',name=prefix+name,parent=destination) for name in ('jointA','jointB')]
            cmds.setAttr(dest_joints[0]+'.translateX',-1.);cmds.setAttr(dest_joints[1]+'.translateX',1.)
            target=cmds.polyPlane(name=prefix+'targetMesh',width=2,height=2,subdivisionsX=5,subdivisionsY=5,constructionHistory=False)[0]
            target=cmds.parent(target,destination)[0]
            plan=service.preview(snapshot,target,root=destination,method='surface',name='Interpolated file import')
            assert plan['report']['complete'] and plan['skin'] is None
            assert all('name' in row['method'].lower() for row in plan['report']['rows'])
            expected=plan['payload'];service.commit(plan);actual=api.context(target);state=api.metadata(actual)[1]
            assert len(state['layers'])==1 and actual['count']==36
            columns={identity:i for i,identity in enumerate(actual['ids'])}
            desired=[0.]*(actual['count']*len(actual['ids']))
            for v in range(actual['count']):
                for j,identity in enumerate(expected['mapping']):desired[v*len(actual['ids'])+columns[identity]]=expected['weights'][v*len(expected['mapping'])+j]
            assert api.same(actual['weights'],desired,2e-6)
            cmds.undo();assert service.mesh(target)['skin'] is None
            cmds.redo();assert api.same(api.context(target)['weights'],desired,2e-6)
            report.update(surface_and_new_binding='passed',namespace=namespace,source=mesh,target=target,status='passed')
    finally:
        cmds.namespace(setNamespace=old_namespace)
        if not keep and cmds.namespace(exists=':'+namespace):cmds.namespace(removeNamespace=':'+namespace,deleteNamespaceContent=True)
        if not keep:api.om.MGlobal.setActiveSelectionList(selection)
    print('Layer Skin Utilities native check:',report)
    return report


def run_large(window=None,subdivisions=160,influences=128,keep=False):
    """Real >2-million-value export/import/Undo fixture; NOT run by pure tests."""
    import array,json,time
    import maya.cmds as cmds
    try:from PySide6 import QtWidgets
    except ImportError:from PySide2 import QtWidgets
    if window is None:
        app=QtWidgets.QApplication.instance()
        matches=[w for w in app.topLevelWidgets() if w.objectName()=='rtkLayerSkinPrototypeWindow' and w.isVisible() and hasattr(w,'utilities')]
        if len(matches)!=1:raise RuntimeError('Open one Layer Skin UI 20 window first.')
        window=matches[0]
    if 'UI 20' not in window.windowTitle():raise RuntimeError('Refresh the complete UI 20 folder before this test.')
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Maya Undo before this test.')
    if not 16<=subdivisions<=400 or not 8<=influences<=512:raise ValueError('Choose 16–400 subdivisions and 8–512 influences.')
    if not window.stop_paint():raise RuntimeError('Save or resolve pending paint before testing.')
    api=window.api;service=window.utilities.backend;io=window.utilities.io
    api.core.storage().dimensions((subdivisions+1)**2,influences)
    selection=api.om.MGlobal.getActiveSelectionList();old_namespace=cmds.namespaceInfo(currentNamespace=True)
    old_pin=window.pin.isChecked();window.pin.setChecked(True)
    namespace='layerSkinProductionIO_'+uuid.uuid4().hex[:8];prefix=':'+namespace+':'
    report={};started=time.perf_counter()
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(add=namespace)
        root=cmds.createNode('transform',name=prefix+'Fixture',skipSelect=True)
        joints=[]
        for i in range(influences):
            joint=cmds.createNode('joint',name=prefix+'joint'+str(i),parent=root,skipSelect=True)
            cmds.setAttr(joint+'.translate',float(i%16)/8.-1.,0.,float(i//16)/8.-1.,type='double3');joints.append(joint)
        mesh=cmds.polyPlane(name=prefix+'mesh',width=2,height=2,subdivisionsX=subdivisions,subdivisionsY=subdivisions,constructionHistory=False)[0]
        mesh=cmds.parent(mesh,root)[0]
        skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,maximumInfluences=4,obeyMaxInfluences=False)[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        ctx=api.context(mesh);count=ctx['count'];width=len(ctx['ids']);expected=array.array('d',ctx['weights'])
        assert count*width>2_000_000,'Increase subdivisions or influence count for this test.'
        with tempfile.TemporaryDirectory(prefix='layer_skin_large_io_') as folder:
            path=os.path.join(folder,'large.rtkskin');report['export']=service.export(mesh,path,include_geometry=False)
            loaded=io.read(path);assert loaded['weights']._rtk_sparse_matrix
            before=array.array('d',[1.]+[0.]*(width-1))*count
            batch=window.session.helper('layer_skin_memory')
            batch.write_weights(type('FixtureWrite',(),dict(vertices=list(range(count)),ctx=ctx,snap_ids=ctx['ids']))(),before,service.owner)
            plan=service.preview(loaded,mesh,root=root,method='id',copy_dq=False,copy_method=False)
            assert plan['report']['complete'];service.commit(plan)
            current=api.context(mesh);assert api.same(current['weights'],expected,2e-6)
            state=api.metadata(current)[1]
            assert state['layers'][-1]['samples']['0']['weights']._rtk_sparse_weights
            cmds.undo();assert api.same(api.context(mesh)['weights'],before,2e-6)
            assert api.metadata(api.context(mesh))[0] is None
            cmds.redo();assert api.same(api.context(mesh)['weights'],expected,2e-6)
        report.update(vertices=count,influences=width,logical_values=count*width,seconds=time.perf_counter()-started,
                      namespace=namespace,native_export_import_undo_redo='passed',mesh=mesh)
    finally:
        cmds.namespace(setNamespace=old_namespace);window.pin.setChecked(old_pin)
        if not keep and cmds.namespace(exists=':'+namespace):cmds.namespace(removeNamespace=':'+namespace,deleteNamespaceContent=True)
        api.om.MGlobal.setActiveSelectionList(selection)
    print('Layer Skin production native check\n'+json.dumps(report,indent=2));return report
