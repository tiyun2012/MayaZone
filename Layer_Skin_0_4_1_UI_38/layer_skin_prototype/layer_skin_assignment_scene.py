"""Frozen hierarchy capture and safe updates of ordinary 0.4.1 Python helpers."""
import hashlib
import math


REVISION=27
GEOMETRY_SOURCE='skin_input_bind'


def joint_roots(owner,ctx):
    """Highest joint ancestors, walking through transform buffers by full path."""
    types={};roots=set();cmds=owner['cmds']
    for dag in ctx['influences']:
        path=dag.fullPathName();root=None
        while path:
            if path not in types:types[path]=cmds.nodeType(path)
            if types[path]=='joint':root=path
            path=path.rsplit('|',1)[0]
        if root:roots.add(root)
    result=[]
    for root in sorted(roots,key=lambda path:(path.count('|'),path)):
        if not any(root.startswith(parent+'|') for parent in result):result.append(root)
    return result


def with_hierarchy(reference,path_ids,geometry):
    """Attach UUID topology; rebuild bone ends from frozen positions only."""
    source=reference['joints'];paths={path:identity for path,identity in path_ids.items() if identity in source}
    by_id={identity:path for path,identity in paths.items()}
    if len(paths)!=len(by_id):raise ValueError('Instanced joint paths cannot share an assignment reference.')
    frames={identity:dict(record,parent=None,ends=[]) for identity,record in source.items()}
    for identity,path in by_id.items():
        parent=path.rsplit('|',1)[0]
        while parent and parent not in paths:parent=parent.rsplit('|',1)[0]
        if parent:frames[identity]['parent']=paths[parent]
    for identity in sorted(frames):
        parent=frames[identity]['parent']
        if parent is not None:frames[parent]['ends'].append(list(frames[identity]['position']))
    for record in frames.values():record['end']=list(record['ends'][0] if record['ends'] else record['position'])
    result=dict(reference,joints=frames,hierarchy_version=1)
    result['key']=geometry.digest(result)
    return result


def matrix_attribute(om,fn,name,index=None):
    plug=fn.findPlug(name,False)
    if index is not None:plug=plug.elementByLogicalIndex(index)
    matrix=om.MFnMatrixData(plug.asMObject()).matrix()
    if matrix.isSingular() or not all(math.isfinite(value) for value in matrix):
        raise ValueError('Invalid skin bind matrix: '+name+('['+str(index)+']' if index is not None else ''))
    return matrix


def input_mesh(owner,ctx):
    """Read the exact skin input, without guessing which intermediate shape is Orig."""
    mesh=ctx.get('input_mesh')
    if mesh is not None:return mesh
    om=owner['om'];fn=ctx['fn'];index=fn.indexForOutputShape(ctx['dag'].node())
    entry=fn.findPlug('input',False).elementByLogicalIndex(index)
    data=next(entry.child(i) for i in range(entry.numChildren())
              if om.MFnAttribute(entry.child(i).attribute()).name=='inputGeometry').asMObject()
    return om.MFnMesh(data)


def capture_reference(owner,ctx):
    """Freeze pre-skin points and bind frames in the same bind-world space."""
    if not all(key in ctx for key in ('fn','skin','dag','influences')):
        raise ValueError('Cannot capture the skin input geometry and matching bind matrices.')
    om=owner['om'];geometry=owner['sibling']('layer_skin_assignment');fn=ctx['fn']
    mesh=input_mesh(owner,ctx);geom_matrix=matrix_attribute(om,fn,'geomMatrix')
    points=[list(point*geom_matrix)[:3] for point in mesh.getPoints(om.MSpace.kObject)]
    if len(points)!=ctx['count']:raise ValueError('Skin input vertex count changed during reference capture.')
    bound={};dags={};paths={};frames={};derived=[]
    for dag in ctx['influences']:
        path=dag.fullPathName()
        try:index=fn.indexForInfluenceObject(dag)
        except TypeError:index=fn.indexForInfluenceObject(dag.node())
        bound[path]=matrix_attribute(om,fn,'bindPreMatrix',index).inverse();dags[path]=dag
    captured=list(owner['reference_joint_paths'](ctx));live={};mesh_world=None
    for dag in captured:dags[dag.fullPathName()]=dag
    def current(path):
        if path not in live:live[path]=dags[path].inclusiveMatrix()
        return live[path]
    for dag in captured:
        path=dag.fullPathName();identity=owner['joint_id'](path)
        if identity in frames:raise ValueError('Instanced joint paths cannot share an assignment reference.')
        if path in bound:matrix=bound[path];source='bind_pre_matrix'
        else:
            ancestor=path.rsplit('|',1)[0]
            while ancestor and ancestor not in bound:ancestor=ancestor.rsplit('|',1)[0]
            if ancestor:
                parent=current(ancestor)
                if parent.isSingular():raise ValueError('Unbound joint reference parent has zero scale: '+ancestor)
                matrix=current(path)*parent.inverse()*bound[ancestor];source='ancestor_bind_offset'
            else:
                if mesh_world is None:mesh_world=ctx['dag'].inclusiveMatrix()
                if mesh_world.isSingular():raise ValueError('Unbound joint reference mesh has zero scale.')
                matrix=current(path)*mesh_world.inverse()*geom_matrix;source='mesh_relative_offset'
            derived.append(identity)
        start=list(om.MPoint(0,0,0)*matrix)[:3]
        record=dict(position=start,end=start,reference_source=source)
        for name,vector in (('x',(1,0,0)),('y',(0,1,0)),('z',(0,0,1))):record[name]=list(om.MVector(*vector)*matrix)
        frames[identity]=record;paths[path]=identity
    reference=dict(points=points,joints=frames,time=float(owner['cmds'].currentTime(query=True)),
                   space='skin input / bind-world / internal cm',geometry_source=GEOMETRY_SOURCE,
                   geometry_source_version=1,geometry_matrix=list(geom_matrix),derived_joints=derived)
    return with_hierarchy(reference,paths,geometry)


def ensure_reference(owner,ctx,state):
    reference=state.get('reference')
    if reference is None:return state
    if reference.get('hierarchy_version') not in (None,1):raise ValueError('Unknown assignment hierarchy version.')
    source=reference.get('geometry_source')
    if source not in (None,GEOMETRY_SOURCE):raise ValueError('Unknown assignment geometry source.')
    if source==GEOMETRY_SOURCE and reference.get('geometry_source_version')!=1:raise ValueError('Unknown assignment geometry source version.')
    if source is None and ctx and all(key in ctx for key in ('skin','fn','dag','mesh')):
        # The next explicit Assign migrates old posed snapshots in its Undo,
        # while opening/refreshing the editor leaves layers and weights intact.
        return dict(state,reference=capture_reference(owner,ctx))
    if reference.get('hierarchy_version')==1:return state
    # Upgrade old saved frames without sampling an animated mesh or joint pose.
    paths={dag.fullPathName():owner['joint_id'](dag.fullPathName()) for dag in owner['reference_joint_paths'](ctx)}
    upgraded=with_hierarchy(reference,paths,owner['sibling']('layer_skin_assignment'))
    return dict(state,reference=upgraded)


def clean_settings(data):
    # Older registered planners still convert radius/length to cm. Remove
    # obsolete values before those planners run; the new generator ignores
    # their numeric defaults. This also supports old scripts with saved settings.
    data['settings']={key:value for key,value in dict(data.get('settings',{})).items()
                      if key not in ('radius','length','falloff','axis_overlap','rule')}


def install(owner):
    """Refresh capture/planning without replacing the MPxCommand or old Undo."""
    if not all(callable(owner.get(name)) for name in ('prepare_edit','reference_joint_paths','joint_id','sibling')):return False
    owner['_layer_skin_assignment_runtime']=globals()
    owner['joint_roots']=lambda ctx:owner['_layer_skin_assignment_runtime']['joint_roots'](owner,ctx)
    owner['reference_capture']=lambda ctx:owner['_layer_skin_assignment_runtime']['capture_reference'](owner,ctx)
    if not owner.get('_layer_skin_assignment_planner'):
        previous=owner['prepare_edit']
        def planner(ctx,meta,state,action,data):
            if action=='assign':owner['_layer_skin_assignment_runtime']['clean_settings'](data)
            if action=='assign' and state and state.get('reference') is not None:
                expected=data.get('expected')
                if expected and expected!=hashlib.sha256(owner['core'].encode(state).encode()).hexdigest():
                    raise ValueError('Layer data changed during the stroke. The unfinished stroke was discarded.')
                state=owner['_layer_skin_assignment_runtime']['ensure_reference'](owner,ctx,state)
                if expected:data['expected']=hashlib.sha256(owner['core'].encode(state).encode()).hexdigest()
            return previous(ctx,meta,state,action,data)
        owner['prepare_edit']=planner;owner['_layer_skin_assignment_planner']=True
        owner['_layer_skin_assignment_settings_cleaner']=True
    elif not owner.get('_layer_skin_assignment_settings_cleaner'):
        previous=owner['prepare_edit']
        def cleaner(ctx,meta,state,action,data):
            if action=='assign':owner['_layer_skin_assignment_runtime']['clean_settings'](data)
            return previous(ctx,meta,state,action,data)
        owner['prepare_edit']=cleaner;owner['_layer_skin_assignment_settings_cleaner']=True
    return True
