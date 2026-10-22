"""Maya API 2.0 weight-editor operations; writes use the shared undoable command."""
import importlib.util
import math
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om

spec=importlib.util.spec_from_file_location('_rtk_skinning_math',os.path.join(os.path.dirname(__file__),'skinning_core.py'))
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
VERSION='0.4.3'
if core.VERSION!=VERSION:raise ImportError('Replace the complete Skinning Tools folder (0.4.3).')


def selected_vertices(api,ctx,whole_mesh=False):
    """Resolve vertices/edges/faces through OpenMaya without altering selection."""
    if whole_mesh:return list(range(ctx['count']))
    selection=om.MGlobal.getActiveSelectionList();result=set();found=False
    for i in range(selection.length()):
        try:path,component=selection.getComponent(i)
        except RuntimeError:continue
        if path.node().hasFn(om.MFn.kTransform):
            try:path=api.mesh_path(path.fullPathName())
            except ValueError:continue
        if path.node()!=ctx['dag'].node():
            if not component.isNull():raise ValueError('Select components from the loaded mesh only.')
            continue
        found=True
        if component.isNull():result.update(range(ctx['count']));continue
        if component.hasFn(om.MFn.kMeshVertComponent):
            fn=om.MFnSingleIndexedComponent(component)
            result.update(range(fn.getCompleteData()) if fn.isComplete else fn.getElements())
        elif component.hasFn(om.MFn.kMeshEdgeComponent):
            it=om.MItMeshEdge(path,component)
            while not it.isDone():result.update((it.vertexId(0),it.vertexId(1)));it.next()
        elif component.hasFn(om.MFn.kMeshPolygonComponent):
            it=om.MItMeshPolygon(path,component)
            while not it.isDone():result.update(it.getVertices());it.next()
        else:raise ValueError('Use mesh vertices, edges, faces or the mesh object.')
    if not found or not result:raise ValueError('Select vertices, edges, faces or the loaded mesh. Whole mesh is an explicit scope option.')
    if any(not 0<=v<ctx['count'] for v in result):raise ValueError('Selected vertex IDs are stale.')
    return sorted(result)


def held_indices(ctx):
    return {i for i,r in enumerate(ctx['influences']) if cmds.attributeQuery('lockInfluenceWeights',node=r['path'],exists=True)
            and cmds.getAttr(r['path']+'.lockInfluenceWeights')}


def row(ctx,vertex):
    width=ctx['width'];return ctx['weights'][vertex*width:(vertex+1)*width]


def rows(ctx,vertices):
    for vertex in vertices:yield row(ctx,vertex)


def inspect(api,mesh,whole_mesh=False,weighted_only=True,neighbors=False):
    with api.planning(True,label='Inspect skin weights') as monitor:
        monitor.stage('Reading skin weights and selection',0);ctx=api.context(mesh,check=monitor.check)
        vertices=selected_vertices(api,ctx,whole_mesh);mean=core.average(rows(ctx,vertices),check=monitor.check);held=held_indices(ctx)
        visible={i for i,v in enumerate(mean) if v>1e-8} if weighted_only else set(range(ctx['width']))
        if neighbors:
            for i in list(visible):
                monitor.check();path=ctx['influences'][i]['path']
                related=(cmds.listRelatives(path,parent=True,fullPath=True,type='joint') or [])+(cmds.listRelatives(path,children=True,fullPath=True,type='joint') or [])
                visible.update(j for j,r in enumerate(ctx['influences']) if r['path'] in related)
        result=[dict(r,index=i,weight=mean[i],held=i in held) for i,r in enumerate(ctx['influences']) if i in visible]
        return {'shape':ctx['shape'],'skin':ctx['skin'],'uuid':ctx['uuid'],'topology':ctx['topology'],
                'vertex_count':len(vertices),'rows':result,'influences':ctx['influences']}


def clipboard(api,mesh,whole_mesh=False):
    with api.planning(True,label='Copy vertex weights') as monitor:
        monitor.stage('Copying average vertex weights',0);ctx=api.context(mesh,check=monitor.check);vertices=selected_vertices(api,ctx,whole_mesh)
        mean=core.average(rows(ctx,vertices),check=monitor.check)
        return {'influences':[dict(r,weight=mean[i]) for i,r in enumerate(ctx['influences']) if mean[i]>1e-12],
                'vertex_count':len(vertices)}


def adjacency(ctx,vertices,check):
    result={};iterator=om.MItMeshVertex(ctx['dag'])
    for v in vertices:
        check();iterator.setIndex(v);result[v]=list(iterator.getConnectedVertices())
    return result


def plan(api,data,progress=True):
    with api.planning(progress,label='Weight edit · '+data.get('action','edit')) as monitor:
        monitor.stage('Reading mesh and skin weights',0);ctx=api.context(data['mesh'],check=monitor.check)
        if data.get('mesh_uuid') and data['mesh_uuid']!=ctx['uuid']:raise ValueError('Loaded mesh changed. Get the mesh again.')
        if data.get('topology') and data['topology']!=ctx['topology']:raise ValueError('Topology changed. Refresh the influence list.')
        vertices=selected_vertices(api,ctx,bool(data.get('whole_mesh')))
        records=ctx['influences'];by_id={r['uuid']:i for i,r in enumerate(records)}
        chosen=data.get('influences',[])
        if len(set(chosen))!=len(chosen) or any(identity not in by_id for identity in chosen):raise ValueError('Influence selection changed. Refresh the list.')
        selected=[by_id[identity] for identity in chosen];locked=held_indices(ctx)
        action=data.get('action');neighbors=None;desired=None;index=None;mapping=None;points=None
        if action not in ('set','nudge','paste','average','smooth','prune','mirror'):raise ValueError('Unknown skin-weight edit action.')
        monitor.stage('Preparing weight edit',15)
        if action in ('average','smooth'):
            neighbors=adjacency(ctx,vertices,monitor.check)
            if action=='average':
                boundary=sorted(set(n for values in neighbors.values() for n in values)-set(vertices))
                if not boundary:raise ValueError('Selection has no outside one-ring boundary. Select a smaller vertex region.')
                desired=core.average(rows(ctx,boundary),check=monitor.check)
        if action=='paste':
            captured=(data.get('clipboard') or {}).get('influences',[])
            if not captured:raise ValueError('Copy vertex weights first.')
            report=api.core.resolve_influences(captured,records,use_distance=False,max_edits=0,ignore_namespace=True,check=monitor.check)
            if not report['complete']:raise ValueError('Clipboard influences must match by UUID or unique exact name. '+ '; '.join(report['errors']))
            desired=[0.]*ctx['width']
            for record,destination in zip(captured,report['mapping']):desired[destination]=float(record['weight'])
        if action=='mirror':
            axis=data.get('axis',0);direction=data.get('direction',1)
            if type(axis) is not int or axis not in (0,1,2) or direction not in (-1,1):raise ValueError('Invalid mirror axis/direction.')
            mapping=core.mirror_mapping(records,data.get('left','_L'),data.get('right','_R'))
            points,triangles=api.sample_geometry(ctx,data.get('geometry','base'),data.get('base',''),check=monitor.check)
            monitor.stage('Preparing mirrored source triangles',25)
            prepared,_=api.core.prepare_triangles(points,triangles,check=monitor.check)
            monitor.stage('Building mirrored source index',35);index=api.core.SurfaceIndex(prepared,check=monitor.check)
            vertices=[v for v in vertices if points[v][axis]*direction < -1e-8]
        strength=float(data.get('strength',1))
        if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Strength must be in [0, 1].')
        changed=[];before=[];after=[];missed=0;width=ctx['width']
        monitor.stage('Calculating edited weight rows',45)
        for number,v in enumerate(vertices):
            monitor.value=45+40*number/max(1,len(vertices));monitor.check();old=row(ctx,v)
            if action in ('set','nudge'):new=core.set_total(old,selected,data.get('value',0),locked,relative=action=='nudge')
            elif action=='prune':new=core.prune(old,data.get('threshold',.001),locked)
            else:
                sample=desired
                if action=='smooth':
                    if not neighbors[v]:continue
                    sample=core.average(rows(ctx,neighbors[v]))
                if action=='mirror':
                    position=list(points[v]);position[axis]*=-1;hit=index.nearest(position,check=monitor.check)
                    if hit is None:missed+=1;continue
                    sample=api.core.interpolate(ctx['weights'],width,hit['ids'],hit['bary'],mapping,width)
                new=core.fit_locked(old,sample,locked)
            new=[a+(b-a)*strength for a,b in zip(old,new)]
            if not api.same(old,new,1e-12):changed.append(v);before.extend(old);after.extend(new)
        monitor.stage('Checking target locks and drivers',90);api.writable(ctx,changed,after,check=monitor.check)
        monitor.stage('Weight edit ready',100)
        return {'ctx':ctx,'vertices':changed,'before':before,'after':after,'before_dq':[],'after_dq':[],'copy_dq':False,
                'summary':{'action':action,'eligible_vertices':len(vertices),'changed_vertices':len(changed),'distance_skips':missed,
                           'held_influences':len(locked),'mesh':ctx['shape']}}


def set_hold(api,mesh,identities,mode):
    """Explicit lock changes only; native commands preserve normal Maya Undo."""
    if mode not in ('hold','unhold','toggle'):raise ValueError('Unknown Hold action.')
    ctx=api.context(mesh,read_weights=False);by_id={r['uuid']:r['path'] for r in ctx['influences']}
    if not identities or any(identity not in by_id for identity in identities):raise ValueError('Choose valid influences; refresh if the skin changed.')
    plugs=[]
    for identity in identities:
        path=by_id[identity];plug=path+'.lockInfluenceWeights'
        if not cmds.objExists(plug):raise ValueError('Influence has no lockInfluenceWeights: '+path)
        if cmds.referenceQuery(path,isNodeReferenced=True) or cmds.getAttr(plug,lock=True) or cmds.listConnections(plug,source=True,destination=False):raise ValueError('Hold attribute is referenced, locked or driven: '+plug)
        current=bool(cmds.getAttr(plug));plugs.append((plug,current,not current if mode=='toggle' else mode=='hold'))
    if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Undo before changing Hold states.')
    cmds.undoInfo(openChunk=True,chunkName='Skinning Hold')
    try:
        try:
            for plug,old,new in plugs:cmds.setAttr(plug,new)
        except Exception:
            for plug,old,new in plugs:cmds.setAttr(plug,old)
            raise
    finally:cmds.undoInfo(closeChunk=True)
    return len(plugs)


def affected_vertices(api,mesh,identities,mode='replace'):
    with api.planning(True,label='Select affected vertices') as monitor:
        monitor.stage('Finding vertices affected by influences',0);ctx=api.context(mesh,check=monitor.check)
        lookup={r['uuid']:i for i,r in enumerate(ctx['influences'])}
        if not identities or any(identity not in lookup for identity in identities):raise ValueError('Select valid influence rows first.')
        columns=[lookup[identity] for identity in identities];vertices=[];width=ctx['width']
        for v in range(ctx['count']):
            monitor.check()
            if any(ctx['weights'][v*width+j]>1e-8 for j in columns):vertices.append(v)
    selection=om.MSelectionList()
    if vertices:selection.add((ctx['dag'],api.components(vertices)))
    modes={'replace':om.MGlobal.kReplaceList,'add':om.MGlobal.kAddToList,'remove':om.MGlobal.kRemoveFromList}
    if mode not in modes:raise ValueError('Unknown vertex selection mode.')
    om.MGlobal.setActiveSelectionList(selection,modes[mode]);return len(vertices)
