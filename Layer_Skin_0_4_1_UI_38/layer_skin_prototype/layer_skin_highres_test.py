"""Reproducible high-resolution checks. --pure needs no Maya.

Inside Maya (UI 8 folder installed):
    import runpy
    test = runpy.run_path(r'D:/dev/MayaZone/layer_skin_prototype41/layer_skin_highres_test.py')
    result = test['run_maya'](subdivisions=316)  # 100,489 vertices; keeps demo

The Maya test creates its own namespace. It does not clear the scene or Undo.
A real mouse brush stroke and visual GPU/color checks remain interactive tests.
"""
import gc
import importlib.util
import json
import math
import os
import time
import uuid


def sibling(name):
    filename=os.path.join(os.path.dirname(globals().get('__file__') or sibling.__code__.co_filename),name+'.py')
    spec=importlib.util.spec_from_file_location('_rtk_highres_'+name,filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def run_pure(vertices=100000,influences=16,iterations=3):
    core=sibling('layer_skin_core');relax=sibling('layer_skin_relax');viewport=sibling('layer_skin_viewport')
    if vertices*influences>core.MAX_VALUES:raise ValueError('This case exceeds the prototype vertex × influence limit.')
    ids=['joint'+str(i) for i in range(influences)]
    state=core.create([1.]+[0.]*(influences-1),1,ids,'temporary')
    state['vertex_count']=vertices;state['topology']='benchmark-grid'
    state['base']=([1.]+[0.]*(influences-1))*vertices
    state=core.edit(state,'add',{'name':'High resolution'})
    layer=state['layers'][0];layer['joints']=ids[:]
    # Every row varies. Quantized input rows are shared; the solver must still
    # process every vertex and allocate its changed results independently.
    bands=[]
    for i in range(64):
        amount=i/63.;bands.append(dict(weights=[1.-amount,amount]+[0.]*(influences-2),coverage=1.))
    layer['samples']={str(v):bands[(v*17)%64] for v in range(vertices)}
    stride=max(2,int(math.sqrt(vertices)))
    graph={v:tuple(u for u in (v-1 if v%stride else -1,v+1 if (v+1)%stride else -1,v-stride,v+stride) if 0<=u<vertices) for v in range(vertices)}
    start=time.perf_counter()
    result,changed=relax.relax_samples(state,layer['id'],graph,range(vertices),iterations,.5,2)
    solve=time.perf_counter()-start
    start=time.perf_counter();core.validate(result);validate=time.perf_counter()-start
    samples=result['layers'][0]['samples'];values=[samples[str(v)]['weights'][1]*samples[str(v)]['coverage'] for v in range(vertices)]
    palette=viewport.Palette();start=time.perf_counter();colors=palette.map(values,'heatmap');ramp=time.perf_counter()-start
    assert len(colors)==vertices and all(0<=value<=1 for value in values)
    start=time.perf_counter()
    roi,_=relax.relax_samples(state,layer['id'],graph,range(min(vertices,1000)),iterations,.5,2)
    roi_seconds=time.perf_counter()-start
    core.validate(roi)
    report=dict(vertices=vertices,influences=influences,iterations=iterations,changed_vertices=len(changed),
                solver_seconds=solve,validation_seconds=validate,palette_seconds=ramp,roi_1000_seconds=roi_seconds,
                excludes='Maya API, CPV upload, skin writes, encoding and viewport/GPU')
    del result,roi,state,graph,samples,colors;gc.collect()
    return report


def run_maya(subdivisions=316,keep=True):
    """Native API assertions + timings. Does not simulate a mouse stroke."""
    import maya.cmds as cmds
    if type(subdivisions) is not int or not 8<=subdivisions<=700:raise ValueError('Choose 8–700 subdivisions.')
    helper=sibling('layer_skin_test');api=helper.editor_api()
    if not hasattr(cmds,'rtkLayerSkin'):raise RuntimeError('Load Layer Skin 0.4.1 and refresh to UI 8 first.')
    if not cmds.undoInfo(query=True,state=True):raise RuntimeError('Enable Undo for the native test.')
    previous_selection=api.om.MGlobal.getActiveSelectionList();previous_tool=cmds.currentCtx()
    import sys
    other=getattr(sys.modules.get('_rtk_layer_skin_paint_041'),'session',None)
    if other is not None:
        other.flush_pending('high_resolution_test');other.stop()
        if previous_tool==api.paint_context:previous_tool='selectSuperContext'
    namespace='layerSkinHighRes_'+uuid.uuid4().hex[:8]
    previous_namespace=cmds.namespaceInfo(currentNamespace=True)
    cmds.namespace(setNamespace=':')
    cmds.namespace(add=namespace)
    cmds.namespace(setNamespace=namespace)
    prefix=':'+namespace+':'
    root=None;mesh=None;session=None;report={}
    def call(action,**data):return cmds.rtkLayerSkin(action=action,data=json.dumps(dict(data,target=mesh)))
    try:
        started=time.perf_counter();root=cmds.createNode('transform',name=prefix+'DEMO')
        joints=[cmds.createNode('joint',name=prefix+label,parent=root) for label in ('left_JNT','right_JNT')]
        cmds.setAttr(joints[0]+'.translateX',-3);cmds.setAttr(joints[1]+'.translateX',3)
        mesh=cmds.polyPlane(name=prefix+'mesh',width=8,height=8,subdivisionsX=subdivisions,subdivisionsY=subdivisions,constructionHistory=False)[0]
        mesh=cmds.parent(mesh,root)[0]
        skin=cmds.skinCluster(joints,mesh,toSelectedBones=True,normalizeWeights=1,maximumInfluences=2,obeyMaxInfluences=False,name=prefix+'skinCluster')[0]
        cmds.setAttr(skin+'.maintainMaxInfluences',False)
        for joint in joints:cmds.setAttr(joint+'.lockInfluenceWeights',False)
        ctx=api.context(mesh);report.update(vertices=ctx['count'],influences=len(ctx['ids']),build_seconds=time.perf_counter()-started)
        call('add',name='High resolution');ctx=api.context(mesh);_,state=api.metadata(ctx);layer=state['layers'][0]['id']
        joint=api.joint_id(joints[1]);values={str(v):float(v%(subdivisions+1)>=subdivisions//2) for v in range(ctx['count'])}
        started=time.perf_counter();call('paint',layer=layer,joint=joint,mode='weights',values=values)
        report['author_seconds']=time.perf_counter()-started
        ctx=api.context(mesh);weights=ctx['weights'][:];fn=api.om.MFnMesh(ctx['dag'])
        color_sets=list(fn.getColorSetNames());history=cmds.listHistory(ctx['shape']) or []
        session=api.make_session();session.start(mesh,layer,joint,'weights',joint_path=joints[1]);session.set_display('heatmap')
        cmds.setToolTo('selectSuperContext')
        assert not session.active and session.viewing,'Tool cleanup did not retain the weight view'
        assert session.preview.visible,session.preview_error
        report['display']=session.preview.report()
        started=time.perf_counter();cmds.refresh(force=True);report['select_view_refresh_seconds']=time.perf_counter()-started
        cmds.selectMode(component=True);cmds.selectType(allComponents=False,polymeshVertex=True)
        cmds.select(mesh+'.vtx[0:99]',replace=True)
        assert session.preview.visible and not cmds.selectMode(query=True,object=True)
        cmds.selectType(allComponents=False,polymeshEdge=True);cmds.select(mesh+'.e[0:99]',replace=True)
        started=time.perf_counter();cmds.refresh(force=True);report['edge_view_refresh_seconds']=time.perf_counter()-started
        selection=api.om.MGlobal.getActiveSelectionList().getSelectionStrings();tool=cmds.currentCtx()
        session.stop(keep_view=True);started=time.perf_counter()
        call('relax',layer=layer,iterations=3,strength=.5,max_new=2,joints=[])
        report['relax_edge_scope_seconds']=time.perf_counter()-started
        relaxed=api.context(mesh)['weights'];session.refresh_view()
        assert session.preview.visible and tool==cmds.currentCtx()
        assert selection==api.om.MGlobal.getActiveSelectionList().getSelectionStrings()
        assert not cmds.selectMode(query=True,object=True)
        session.stop(keep_view=True);cmds.undo();assert api.same(api.context(mesh)['weights'],weights,2e-6)
        cmds.redo();assert api.same(api.context(mesh)['weights'],relaxed,2e-6);session.refresh_view()
        session.before_file_io()
        fn.syncObject()
        assert list(fn.getColorSetNames())==color_sets,'Temporary colors survived before-save cleanup'
        assert (cmds.listHistory(ctx['shape']) or [])==history,'Temporary preview history survived cleanup'
        session.after_file_io();assert session.preview.visible
        session.start(mesh,layer,joint,'weights',joint_path=joints[1])
        assert session.active and cmds.currentCtx()==api.paint_context and session.buffer.geometry_sources()
        report.update(status='passed',namespace=namespace,mesh=mesh,interactive_check='Paint, Shift-relax weights/mask, B-drag radius, Esc, one-step Undo; Flood then Assign; Q, F9/F10 and switch joints. Verify viewport colors. See RELAX_GUIDE.md.')
    finally:
        if session:session.close()
        cmds.namespace(setNamespace=previous_namespace)
        if not keep and cmds.namespace(exists=':'+namespace):
            cmds.namespace(removeNamespace=':'+namespace,deleteNamespaceContent=True)
        if keep and mesh and cmds.objExists(mesh):
            cmds.selectMode(object=True);cmds.select(mesh,replace=True)
        else:api.om.MGlobal.setActiveSelectionList(previous_selection)
        if cmds.currentCtx()!=previous_tool:cmds.setToolTo(previous_tool)
    print('Layer Skin high-resolution check\n'+json.dumps(report,indent=2))
    return report


def run_brush_pure(vertices=250000,influences=8,stamps=40,radius=12.):
    """Large backing mesh with local stamps; excludes native/API/preview costs."""
    core=sibling('layer_skin_core');relax=sibling('layer_skin_relax');brush=sibling('layer_skin_brush')
    if vertices*influences>core.MAX_VALUES or influences<2:raise ValueError('Choose 2+ influences within the dense-value guard.')
    stride=max(2,int(math.sqrt(vertices)));ids=['joint'+str(i) for i in range(influences)]
    state=core.create([1.]+[0.]*(influences-1),1,ids,'temporary')
    state.update(vertex_count=vertices,base=([1.]+[0.]*(influences-1))*vertices)
    state=core.edit(state,'add',dict(name='Brush benchmark'));layer=state['layers'][0];layer['joints']=ids[:]
    bands=[dict(weights=[1.-i/63.,i/63.]+[0.]*(influences-2),coverage=1.) for i in range(64)]
    layer['samples']={str(v):bands[(v*17)%64] for v in range(vertices)}
    points=[(float(v%stride),float(v//stride),0.) for v in range(vertices)];rows={}
    def neighbors(v):
        if v not in rows:
            rows[v]=tuple(u for u in (v-1 if v%stride else -1,v+1 if (v+1)%stride else -1,v-stride,v+stride) if 0<=u<vertices)
        return rows[v]
    start=time.perf_counter();grid=brush.SurfaceGrid(points,radius);grid_seconds=time.perf_counter()-start
    start=time.perf_counter()
    stroke=brush.RelaxStroke(state,layer['id'],'weights',dict(iterations=1,strength=.5,opacity=.7,max_new=2,preserve_coverage=True),relax)
    snapshot_seconds=time.perf_counter()-start;counts=[];start=time.perf_counter()
    for i in range(stamps):
        center=(stride*.5+i*.4,stride*.5,0.);seed=int(round(center[1]))*stride+int(round(center[0]))
        factors=grid.footprint(center,[seed],neighbors);counts.append(len(factors));stroke.stamp(factors,neighbors)
    stamp_seconds=time.perf_counter()-start
    start=time.perf_counter();payload=stroke.payload();payload_seconds=time.perf_counter()-start
    core.validate(stroke.working)
    report=dict(vertices=vertices,influences=influences,stamps=stamps,radius=radius,
        footprint_vertices_min=min(counts),footprint_vertices_max=max(counts),changed_vertices=len(payload['samples']),
        cached_neighbor_rows=len(rows),position_grid_seconds=grid_seconds,snapshot_seconds=snapshot_seconds,
        footprint_and_solver_seconds=stamp_seconds,mean_stamp_seconds=stamp_seconds/stamps,payload_seconds=payload_seconds,
        excludes='Maya geometry extraction/raycast, native preview-array upload, skin writes/readback, metadata encoding and viewport/GPU')
    del state,stroke,grid,points,rows;gc.collect();return report


if __name__=='__main__':
    import sys
    if '--pure' in sys.argv:
        print(json.dumps(dict(flood=[run_pure(100000,16),run_pure(250000,8)],brush=run_brush_pure()),indent=2))
