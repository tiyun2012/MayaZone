"""Bounded native skin reads/writes and a safe 0.4.1 owner refresh."""
import array
import importlib.util
import os
import sys


def storage():
    key='_rtk_layer_skin_storage_20'
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,os.path.join(os.path.dirname(__file__),'layer_skin_storage.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[key]=module
    return sys.modules[key]


def component(om, vertices):
    fn=om.MFnSingleIndexedComponent();value=fn.create(om.MFn.kMeshVertComponent)
    fn.addElements(vertices);return value


def read_weights(fn, dag, count, width, om, check=None):
    values=storage().dimensions(count,width)
    result=storage().empty_values(values)
    step=max(1,storage().CHUNK_VALUES//width)
    for start in range(0,count,step):
        if check:check()
        end=min(count,start+step)
        block,actual_width=fn.getWeights(dag,component(om,range(start,end)))
        if actual_width!=width or len(block)!=(end-start)*width:
            raise ValueError('Influence table changed while reading skin weights.')
        result.extend(block)
    return result


def context(owner,target):
    cmds=owner['cmds'];om=owner['om'];oma=owner['oma']
    nodes=cmds.ls(target,long=True,objectsOnly=True) or []
    if len(nodes)!=1:raise ValueError('Get one skinned polygon mesh.')
    node=nodes[0]
    shapes=[node] if cmds.nodeType(node)=='mesh' else (cmds.listRelatives(node,shapes=True,noIntermediate=True,fullPath=True) or [])
    shapes=[shape for shape in shapes if cmds.nodeType(shape)=='mesh']
    if len(shapes)!=1:raise ValueError('Choose a transform with one polygon mesh shape.')
    selection=om.MSelectionList();selection.add(shapes[0]);dag=selection.getDagPath(0)
    if dag.isInstanced():raise ValueError('Instanced meshes are not supported.')
    history=cmds.listHistory(shapes[0],pruneDagObjects=True) or []
    skins=list(dict.fromkeys(cmds.ls(history,type='skinCluster') or [])) if history else []
    if len(skins)!=1:raise ValueError('Layer Skin requires exactly one skinCluster in the mesh history.')
    fn=oma.MFnSkinCluster(owner['obj'](skins[0]));index=fn.indexForOutputShape(dag.node())
    input_plug=fn.findPlug('input',False).elementByLogicalIndex(index)
    data=next(input_plug.child(i) for i in range(input_plug.numChildren())
              if om.MFnAttribute(input_plug.child(i).attribute()).name=='inputGeometry').asMObject()
    input_mesh=om.MFnMesh(data);output_mesh=om.MFnMesh(dag)
    signature=owner['topology'](input_mesh)
    if signature!=owner['topology'](output_mesh):raise ValueError('Topology-changing history after skinning is not supported.')
    influences=fn.influenceObjects();count=input_mesh.numVertices
    weights=read_weights(fn,dag,count,len(influences),om,owner.get('_layer_skin_io_check'))
    ids=[om.MFnDependencyNode(path.node()).uuid().asString() for path in influences]
    return dict(shape=dag.fullPathName(),dag=dag,skin=skins[0],fn=fn,count=count,
                influences=influences,ids=ids,topology=signature,weights=weights,mesh=output_mesh,input_mesh=input_mesh,
                uuid=om.MFnDependencyNode(dag.node()).uuid().asString())


def write_weights(command, weights, owner):
    if not command.vertices:return
    om=owner['om'];fn=command.ctx['fn'];dag=command.ctx['dag']
    ids=[om.MFnDependencyNode(path.node()).uuid().asString() for path in fn.influenceObjects()]
    live={identity:i for i,identity in enumerate(ids)}
    if len(live)!=len(command.snap_ids) or any(identity not in live for identity in command.snap_ids):
        raise RuntimeError('Influence membership changed outside Undo. Restore the matching skin before Undo/Redo.')
    columns=[live[identity] for identity in command.snap_ids];width=len(columns)
    if len(weights)!=len(command.vertices)*width:raise ValueError('Native weight snapshot dimensions changed.')
    step=max(1,storage().CHUNK_VALUES//width)
    for start in range(0,len(command.vertices),step):
        rows=command.vertices[start:start+step];comp=component(om,rows)
        values=om.MDoubleArray(weights[start*width:(start+len(rows))*width])
        fn.setWeights(dag,comp,om.MIntArray(columns),values,False)
        actual,actual_width=fn.getWeights(dag,comp)
        if actual_width!=width or len(actual)!=len(values):raise RuntimeError('Maya changed the skin influence table during a write.')
        ordered=actual if columns==list(range(width)) else array.array('d',
            (actual[i*width+col] for i in range(len(rows)) for col in columns))
        if not owner['same'](ordered,values,2e-6):
            raise RuntimeError('Maya changed the requested weights; operation cannot be accepted.')


def install(owner):
    """Refresh normal Python helpers, keeping MPxCommand and old Undo objects."""
    previous=owner.get('context')
    if not callable(previous) or 'oma' not in owner:return False
    source=getattr(getattr(previous,'__code__',None),'co_filename','').replace('\\','/').rsplit('/',1)[-1]
    if not getattr(previous,'_layer_skin_native_context',False) and not getattr(previous,'_layer_skin_memory_revision',False) and source!='layer_skin_test.py':
        return False  # A custom editor API owns its own context implementation.
    def read(target):return context(owner,target)
    read._layer_skin_memory_revision=20
    owner['context']=read
    cls=owner.get('LayerCommand')
    if cls is not None:
        current=cls.write
        base=getattr(current,'_layer_skin_io_original',current)
        if getattr(base,'_layer_skin_memory_revision',None)!=20:
            def write(command,weights):return write_weights(command,weights,owner)
            write._layer_skin_memory_revision=20
            cls.write=write
            # The IO extension must wrap this new ordinary write helper once,
            # so auxiliary DQ/method Undo still follows each native write.
            owner['_skin_io_runtime']=None
    owner['_layer_skin_memory_revision']=20
    return True
