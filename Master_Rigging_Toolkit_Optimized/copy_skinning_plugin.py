"""Undoable Copy Skinning command; Python API 2.0. No per-frame callbacks."""
import array
import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from types import SimpleNamespace
from contextlib import contextmanager,nullcontext
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

core=None


def _load_core(plugin_path=None,required=True):
    """Maya's Python plug-in loader does not always populate __file__."""
    global core
    if core is not None:return core
    # co_filename is set when Maya compiles the file, even without __file__.
    # initializePlugin supplies Maya's authoritative loadPath as a fallback.
    locations=[plugin_path,globals().get('__file__'),_load_core.__code__.co_filename]
    for location in locations:
        if not location or (not os.path.isfile(location) and not os.path.isdir(location)):continue
        directory=location if os.path.isdir(location) else os.path.dirname(os.path.abspath(location))
        filename=os.path.join(directory,'copy_skinning_core.py')
        if not os.path.isfile(filename):continue
        spec=importlib.util.spec_from_file_location('_rtk_copy_skin_core_01',filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if getattr(module,'VERSION',None)!='0.4.3':
            raise ImportError('Copy Skinning files are from different versions. Replace the complete folder: core, plugin and UI must all be version 0.4.3.')
        core=module
        return core
    if required:
        raise ImportError('Copy Skinning cannot find copy_skinning_core.py beside the plug-in. Extract the complete Copy_Skinning folder and keep its Python files together.')
    return None


# Ordinary imports (UI/tests) can use the helpers immediately. If Maya supplies
# neither a usable __file__ nor co_filename, defer to initializePlugin.loadPath.
_load_core(required=False)
COMMAND='rtkCopySkin'
MAX_VALUES=4_000_000
MASKS={'source':'rtkCopySkin_sourceMask','target':'rtkCopySkin_targetMask'}
_active_plan=False
_editor=None


def cache_service():
    # Maya registers the command in a different module from the panel helper.
    # Share only plain Python cached data between both entry points.
    name='_rtk_copy_skin_cache_043'
    module=sys.modules.get(name)
    if module is None:
        filename=os.path.join(os.path.dirname(core.__file__),'copy_skinning_cache.py')
        if not os.path.isfile(filename):raise ImportError('Missing copy_skinning_cache.py. Replace the complete Skinning Tools 0.4.3 folder.')
        spec=importlib.util.spec_from_file_location(name,filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if module.VERSION!='0.4.3':raise ImportError('Cache files differ. Replace the complete Skinning Tools 0.4.3 folder.')
        sys.modules[name]=module
    return module.CACHE


def cache_stats():return cache_service().stats()


def clear_cache():cache_service().clear()


def task_module():
    name='_rtk_skinning_tasks_043';module=sys.modules.get(name)
    if module is None:
        filename=os.path.join(os.path.dirname(core.__file__),'skinning_tasks.py')
        if not os.path.isfile(filename):raise ImportError('Missing skinning_tasks.py. Replace the complete Skinning Tools 0.4.3 folder.')
        spec=importlib.util.spec_from_file_location(name,filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if module.VERSION!='0.4.3':raise ImportError('Replace the complete Skinning Tools 0.4.3 folder, including skinning_tasks.py.')
        sys.modules[name]=module
    return module


def task_service():return task_module().SERVICE


def native_progress_info():
    # Query only; never reserve or close a window while listing tasks.
    try:
        title=cmds.progressWindow(query=True,title=True);status=cmds.progressWindow(query=True,status=True)
        if not title and not status:return None
        return dict(title=str(title or ''),status=str(status or ''),progress=cmds.progressWindow(query=True,progress=True))
    except RuntimeError:return None


def task_report():
    result=task_service().snapshot();result['maya_progress']=native_progress_info();return result


def stop_task(identity,force=False,expected_progress=None):
    service=task_service()
    if identity!='maya-progress':return service.request_stop(identity,force)
    if not force:raise ValueError('The owner of this Maya progress window is unknown. Use Force stop / reset to close its progress UI.')
    if service.active:raise ValueError('A tracked task is active. Request its cancellation; its progress cannot be reset during execution.')
    current=native_progress_info()
    if not current:return 'No Maya progress window is currently available.'
    if expected_progress!=current:raise ValueError('Maya progress changed. Refresh and inspect the selected row before resetting.')
    cmds.progressWindow(endProgress=True)
    return 'Maya progress UI reset. This does not terminate the script that created it or interrupt a native call.'


def skin_input(fn,index):
    """Read evaluated input data, including tweaks/deformers before this skin."""
    element=fn.findPlug('input',False).elementByLogicalIndex(index)
    for i in range(element.numChildren()):
        plug=element.child(i)
        if om.MFnAttribute(plug.attribute()).name=='inputGeometry':
            data=plug.asMObject()
            if data.isNull():raise ValueError('Skin input has no polygon mesh data: '+plug.name())
            return om.MFnMesh(data),plug.name()
    raise ValueError('Cannot resolve the skin inputGeometry plug.')


def mesh_input(dag):
    # Query wiring without attaching MFnMesh or evaluating any geometry data.
    return om.MFnDependencyNode(dag.node()).findPlug('inMesh',False)


def no_skin(dag):
    return ValueError('Mesh has no skinCluster: '+dag.fullPathName()+'. Copy Skinning needs a source with skin weights. For an unskinned target, use Prepare target / refresh mapping.')


def find_skin(dag,check=None):
    """Inspect upstream dependencies before any mesh evaluation; fail closed."""
    root=mesh_input(dag)
    if not root.isDestination:raise no_skin(dag)
    if check:check()
    started=time.monotonic();skins=set();steps=0
    # No type filter: each visited plug returns control for cancellation instead
    # of searching an entire history internally for the next matching skin.
    graph=om.MItDependencyGraph(root,om.MFn.kInvalid,om.MItDependencyGraph.kUpstream,
                               om.MItDependencyGraph.kDepthFirst,om.MItDependencyGraph.kPlugLevel)
    while not graph.isDone():
        if check:check()
        if steps>=10000 or time.monotonic()-started>120:
            raise ValueError('Skin discovery limit reached for '+dag.fullPathName()+'. Geometry was not read. Inspect the mesh history before retrying.')
        steps+=1;node=graph.currentNode()
        if node.isNull():raise ValueError('Cannot validate an unknown node in mesh history: '+dag.fullPathName())
        if node.hasFn(om.MFn.kSkinClusterFilter):
            skins.add(om.MFnDependencyNode(node).name())
            if len(skins)>1:raise ValueError('Multiple skinClusters in mesh history are unsupported: '+dag.fullPathName())
        graph.next()
    if not skins:raise no_skin(dag)
    return next(iter(skins))


def load_mesh(name,mode='base',override='',source=False,method='surface',max_seconds=120):
    dag=mesh_path(name)
    # Bare, unskinned meshes must not create progress/interrupt scopes at all.
    if not mesh_input(dag).isDestination:raise no_skin(dag)
    with planning(True,max_seconds,label='Load '+('source' if source else 'target')+' · '+name.rsplit('|',1)[-1]) as monitor:
        monitor.stage('Checking mesh for a skinCluster',0);ctx=context(name,read_weights=False,check=monitor.check)
        if method!='id':
            monitor.stage('Validating and caching geometry',25);points,triangles=sample_geometry(ctx,mode,override,check=monitor.check)
            if source and len(triangles)*1900<=cache_service().max_bytes:
                monitor.stage('Caching source surface index',55)
                cache_service().surface(core,points,triangles,None,.001,ctx.get('sample_key'),monitor.check)
        return dict(shape=ctx['shape'],uuid=ctx['uuid'],skin=ctx['skin'],vertices=ctx['count'],influences=ctx['width'],
                    input_geometry=ctx['input_plug'],geometry=mode,cache=cache_stats())


def load_editor():
    global _editor
    if _editor is None:
        filename=os.path.join(os.path.dirname(core.__file__),'skinning_backend.py')
        if not os.path.isfile(filename):raise ImportError('Skinning Tools requires skinning_backend.py and skinning_core.py. Replace the complete folder.')
        spec=importlib.util.spec_from_file_location('_rtk_skinning_editor_backend',filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if module.VERSION!='0.4.3':raise ImportError('Replace the complete Skinning Tools 0.4.3 folder.')
        _editor=module
    return _editor


def editor_api():
    return SimpleNamespace(core=core,planning=planning,context=context,mesh_path=mesh_path,
        sample_geometry=sample_geometry,writable=writable,same=same,components=components)


def edit_plan(data,progress=False,monitor=None):
    api=editor_api()
    if monitor is not None:api.planning=lambda *args,**kwargs:nullcontext(monitor)
    return load_editor().plan(api,data,progress)


def make_interrupt_monitor():
    # MComputation is available through Maya's legacy OpenMaya utility API;
    # all mesh/skin access remains API 2.0. It polls Maya's native Escape signal.
    import maya.OpenMaya as legacy
    return legacy.MComputation()


class PlanProgress:
    """Own one Maya progress window through calculation and the final native action."""
    def __init__(self,enabled,max_seconds=0):
        self.enabled=enabled;self.owned=False;self.status='Starting';self.value=0
        self.last=-float('inf');self.started=time.monotonic();self.interrupt=None
        self.service=None;self.task_id=None;self.label='Skinning operation';self.outcome='Completed';self.error=''
        self.max_seconds=float(max_seconds)
        if not math.isfinite(self.max_seconds) or self.max_seconds<0:raise ValueError('Calculation time limit must be nonnegative; 0 means unlimited.')
    def start(self):
        self.service=task_service();self.task_id=self.service.begin(self.label)
        if self.enabled:
            self.owned=bool(cmds.progressWindow(title=self.label,status='Starting',
                minValue=0,maxValue=100,progress=0,isInterruptable=True))
            if not self.owned:
                info=native_progress_info()
                raise RuntimeError('Maya could not create a progress window. Open Tasks to inspect or reset it. '+('Existing progress: '+info['title']+' · '+info['status'] if info else 'No progress owner could be identified.'))
            self.service.mark_progress(self.task_id,True)
            self.interrupt=make_interrupt_monitor()
            self.interrupt.beginComputation(False,True,False)
    def stage(self,status,value):
        self.status=status;self.value=value;self.last=-float('inf');self.check()
    def check(self):
        if self.task_id:self.service.checkpoint(self.task_id,self.status,self.value)
        now=time.monotonic()
        if self.max_seconds and now-self.started>self.max_seconds:
            raise RuntimeError('Copy Skinning calculation time limit ({:.0f}s) reached during: {}. No target weights were written. Increase Calculation time limit or set it to 0 for unlimited.'.format(self.max_seconds,self.status))
        if not self.owned:return
        if now-self.last<.1:return
        self.last=now
        # Poll Maya's native interrupt monitor and dialog flag without pumping
        # arbitrary Qt/idle events that could edit the scene during calculation.
        cmds.progressWindow(edit=True,progress=int(self.value),
            status='{} · {:.0f}s · Esc to cancel'.format(self.status,now-self.started))
        if ((self.interrupt is not None and self.interrupt.isInterruptRequested())
                or cmds.progressWindow(query=True,isCancelled=True)):
            raise RuntimeError('Copy Skinning cancelled before any weight writes.')
    def finish_interrupt(self):
        if self.interrupt is not None:
            interrupt=self.interrupt;self.interrupt=None;interrupt.endComputation()
    def begin_write(self):
        if self.task_id:self.service.begin_write(self.task_id)
        self.finish_interrupt()
    def close(self):
        try:
            try:self.finish_interrupt()
            finally:
                if self.owned:
                    self.owned=False;cmds.progressWindow(endProgress=True)
        except BaseException as exc:
            self.outcome='Failed';self.error=str(exc);raise
        finally:
            if self.task_id:
                identity=self.task_id;self.task_id=None;self.service.finish(identity,self.outcome,self.error)


@contextmanager
def planning(progress,max_seconds=0,label='Skinning operation'):
    global _active_plan
    if _active_plan:raise RuntimeError('Copy Skinning is already calculating. Wait or press Esc to cancel.')
    monitor=PlanProgress(progress,max_seconds);monitor.label=label;_active_plan=True
    try:
        monitor.start();yield monitor
    except BaseException as exc:
        monitor.outcome='Cancelled' if 'cancel' in str(exc).lower() or isinstance(exc,KeyboardInterrupt) else 'Failed';monitor.error=str(exc);raise
    finally:
        try:monitor.close()
        finally:_active_plan=False


def preview_mapping(data):
    with planning(True,label='Match influences') as monitor:
        monitor.stage('Reading meshes and matching influences',0)
        return mapping_report(data,check=monitor.check)


def maya_useNewAPI():pass


def object_(name):
    selection=om.MSelectionList();selection.add(name);return selection.getDependNode(0)


def mesh_path(name):
    names=cmds.ls(name,long=True,objectsOnly=True) or []
    if len(names)!=1:raise ValueError('Get one polygon mesh: '+str(name))
    shapes=[names[0]] if cmds.nodeType(names[0])=='mesh' else (cmds.listRelatives(names[0],shapes=True,noIntermediate=True,fullPath=True) or [])
    shapes=[s for s in shapes if cmds.nodeType(s)=='mesh']
    if len(shapes)!=1:raise ValueError('Expected one polygon mesh shape.')
    selection=om.MSelectionList();selection.add(shapes[0]);path=selection.getDagPath(0)
    if path.isInstanced():raise ValueError('Instanced meshes are not supported.')
    return path


def signature(mesh):
    digest=hashlib.sha256();digest.update(str(mesh.numVertices).encode('ascii'))
    for values in mesh.getVertices():digest.update(array.array('q',values).tobytes())
    return digest.hexdigest()


def components(vertices):
    fn=om.MFnSingleIndexedComponent();value=fn.create(om.MFn.kMeshVertComponent);fn.addElements(vertices);return value


def context(name,read_weights=True,check=None):
    dag=mesh_path(name);shape=dag.fullPathName();skin=find_skin(dag,check)
    if check:check()
    fn=oma.MFnSkinCluster(object_(skin));index=fn.indexForOutputShape(dag.node())
    if check:check()
    mesh=om.MFnMesh(dag)
    original,input_plug=skin_input(fn,index)
    topology=signature(mesh)
    if signature(original)!=topology:raise ValueError('Topology-changing history after skinning is unsupported: '+shape)
    paths=fn.influenceObjects();count=mesh.numVertices
    if count*len(paths)>MAX_VALUES:raise ValueError('Transfer memory guard: at most 4 million vertex/influence values per mesh.')
    weights,width=fn.getWeights(dag,components(range(count))) if read_weights else ([],len(paths))
    if width!=len(paths):raise ValueError('Influences changed while reading.')
    records=[{'uuid':om.MFnDependencyNode(p.node()).uuid().asString(),'path':p.fullPathName()} for p in paths]
    return {'dag':dag,'shape':shape,'mesh':mesh,'fn':fn,'skin':skin,'count':count,'width':width,
            'influences':records,'weights':list(weights),'topology':topology,
            'uuid':om.MFnDependencyNode(dag.node()).uuid().asString(),'original':original,
            'skin_uuid':fn.uuid().asString(),'input_plug':input_plug,'input_index':index}


def sample_geometry(ctx,mode,override='',check=None):
    identity=(ctx['uuid'],ctx['skin_uuid'],mode)
    if mode=='current':
        mesh=ctx['mesh'];matrix=ctx['dag'].inclusiveMatrix()
    elif mode=='base':
        if override:
            path=mesh_path(override);mesh=om.MFnMesh(path);matrix=path.inclusiveMatrix()
            identity=identity+(om.MFnDependencyNode(path.node()).uuid().asString(),)
        else:
            mesh,_=skin_input(ctx['fn'],ctx['input_index']);matrix=ctx['dag'].inclusiveMatrix()
        if signature(mesh)!=ctx['topology']:raise ValueError('Base mesh must preserve vertex IDs and face connectivity.')
    else:raise ValueError('Unknown geometry mode.')
    raw=mesh.getPoints(om.MSpace.kObject)
    local=[]
    for number,p in enumerate(raw):
        if check and number%512==0:check()
        local.append(tuple(p)[:3])
    if any(not all(math.isfinite(v) for v in p) for p in local):raise ValueError('Nonfinite mesh positions.')
    cache=cache_service();token=cache.geometry_token(identity,ctx['topology'],local,tuple(matrix),check)
    ctx['sample_key']=token
    cached=cache.get(('geometry',token))
    if cached is not None:return cached
    points=[]
    for number,p in enumerate(raw):
        if check and number%512==0:check()
        points.append(tuple(p*matrix)[:3])
    if any(not all(math.isfinite(v) for v in p) for p in points):raise ValueError('Nonfinite mesh positions.')
    counts,indices=mesh.getTriangles();triangles=[];offset=0
    for face,count in enumerate(counts):
        if check and face%128==0:check()
        for _ in range(count):triangles.append((face,tuple(indices[offset:offset+3])));offset+=3
    result=(points,triangles);cache.put(('geometry',token),result,len(points)*192+len(triangles)*256)
    return result


def capture_region(name,source=False):
    ctx=context(name);faces=set();vertices=set();selection=om.MGlobal.getActiveSelectionList()
    for i in range(selection.length()):
        try:path,component=selection.getComponent(i)
        except RuntimeError:continue
        if component.isNull():continue
        if path.node().hasFn(om.MFn.kTransform):path.extendToShape()
        if path.node()!=ctx['dag'].node():raise ValueError('Components must belong to the loaded mesh.')
        ids=om.MFnSingleIndexedComponent(component).getElements()
        if component.hasFn(om.MFn.kMeshPolygonComponent):
            faces.update(ids)
            for face in ids:vertices.update(ctx['mesh'].getPolygonVertices(face))
        elif not source and component.hasFn(om.MFn.kMeshVertComponent):vertices.update(ids)
        else:raise ValueError('Source: select faces. Target: select faces or vertices.')
    if (not faces if source else not vertices):raise ValueError('No usable components selected.')
    return {'uuid':ctx['uuid'],'topology':ctx['topology'],'faces':sorted(faces),'vertices':sorted(vertices)}


def region(ctx,value,source=False):
    if not value:return None
    if value['uuid']!=ctx['uuid'] or value['topology']!=ctx['topology']:raise ValueError('Captured region is stale. Get the selection again.')
    ids=value['faces'] if source else value['vertices']
    limit=ctx['mesh'].numPolygons if source else ctx['count']
    if not ids or any(type(i) is not int or not 0<=i<limit for i in ids):raise ValueError('Invalid captured component IDs.')
    return set(ids)


def mask_values(ctx,role):
    name=MASKS[role]
    if name not in ctx['mesh'].getColorSetNames():raise ValueError('Create and paint the '+role+' mask first.')
    colors=ctx['mesh'].getVertexColors(colorSet=name)
    if len(colors)!=ctx['count']:raise ValueError('Mask size mismatch.')
    values=[float(c.r) for c in colors]
    if any(not math.isfinite(v) for v in values):raise ValueError('Nonfinite painted mask values.')
    return [max(0.,min(1.,v)) for v in values]


def same(a,b,tolerance=1e-7):return len(a)==len(b) and all(abs(x-y)<=tolerance for x,y in zip(a,b))


def influence_positions(ctx,space='bind'):
    """Joint origins in world centimeters; bind positions come from bindPreMatrix."""
    if space not in ('bind','current'):raise ValueError('Joint position mode must be bind or current.')
    paths=ctx['fn'].influenceObjects();records=[]
    if len(paths)!=len(ctx['influences']):raise ValueError('Influence list changed while building mapping. Refresh the table.')
    for record,path in zip(ctx['influences'],paths):
        if om.MFnDependencyNode(path.node()).uuid().asString()!=record['uuid']:
            raise ValueError('Influence order changed while reading joint positions. Refresh the table.')
        if space=='current':matrix=path.inclusiveMatrix()
        else:
            try:logical=ctx['fn'].indexForInfluenceObject(path)
            except TypeError:logical=ctx['fn'].indexForInfluenceObject(path.node())
            values=cmds.getAttr(ctx['skin']+'.bindPreMatrix[{}]'.format(logical))
            if len(values)==1 and isinstance(values[0],(list,tuple)):values=values[0]
            matrix=om.MMatrix(values)
            if matrix.isSingular():raise ValueError('Singular bind matrix for '+record['path']+'. Use valid bind data or Current joint positions.')
            matrix=matrix.inverse()
        position=tuple(matrix)[12:15]
        if len(position)!=3 or any(not math.isfinite(v) for v in position):raise ValueError('Invalid influence matrix: '+record['path'])
        records.append(dict(record,position=position))
    return records


def mapping_report(data,source=None,target=None,check=None):
    if check:check()
    source=source or context(data['source'],read_weights=False,check=check);target=target or context(data['target'],read_weights=False,check=check)
    if check:check()
    use_distance=bool(data.get('match_distance',True));left=source['influences'];right=target['influences']
    if use_distance and not {r['uuid'] for r in left}.issubset({r['uuid'] for r in right}):
        left=influence_positions(source,data.get('joint_space','bind'));right=influence_positions(target,data.get('joint_space','bind'))
    tolerance=float(data.get('joint_tolerance',.01))
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('Joint tolerance must be nonnegative.')
    tolerance=om.MDistance(tolerance,om.MDistance.uiUnit()).asCentimeters()
    return core.resolve_influences(left,right,use_name=bool(data.get('match_name',True)),use_distance=use_distance,
                                   tolerance=tolerance,max_edits=data.get('name_edits',3),search=data.get('search',''),replace=data.get('replace',''),
                                   ignore_namespace=bool(data.get('ignore_namespace',True)),manual=data.get('manual_mapping'),check=check)


def validate_mapping_review(report,review):
    if not review:return
    if (set(review.get('source_ids',[]))!=set(report['source_ids']) or set(review.get('target_ids',[]))!=set(report['target_ids'])
            or review.get('pairs')!={r['source_uuid']:r['target_uuid'] for r in report['rows']}):
        raise ValueError('Influence mapping changed since review. Build / refresh mapping and inspect the updated rows.')


def blocked_weight_channel(name,vertices,copy_dq=False):
    """Match long attribute paths; a parent lock/connection blocks its descendants."""
    for root in ('weightList','blendWeights') if copy_dq else ('weightList',):
        if name==root or name.startswith(root+'.'):return True
        if name.startswith(root+'['):
            try:index=int(name[len(root)+1:].split(']',1)[0])
            except ValueError:raise ValueError('Cannot validate target weight channel: '+name)
            return index in vertices
    return False


def writable(ctx,vertices,after,copy_dq=False,check=None):
    for node in (ctx['skin'],ctx['shape']):
        if cmds.referenceQuery(node,isNodeReferenced=True) or om.MFnDependencyNode(object_(node)).isLocked:raise ValueError('Target is referenced or locked: '+node)
    for node in cmds.listConnections(ctx['skin']+'.message',source=False,destination=True,type='network') or []:
        if cmds.attributeQuery('rtkLayerSkinData',node=node,exists=True):raise ValueError('Target has an active Layer Skin stack. Bake/detach it before copying weights.')
    if cmds.getAttr(ctx['skin']+'.maintainMaxInfluences'):raise ValueError('Turn off target Maintain Max Influences before transfer.')
    for j,record in enumerate(ctx['influences']):
        if check:check()
        path=record['path']
        if cmds.attributeQuery('lockInfluenceWeights',node=path,exists=True) and cmds.getAttr(path+'.lockInfluenceWeights'):
            for i,v in enumerate(vertices):
                if check and i%256==0:check()
                if abs(ctx['weights'][v*ctx['width']+j]-after[i*ctx['width']+j])>1e-12:
                    raise ValueError('Target influence is locked: '+path)
    if not vertices:return
    affected=set(vertices)
    for name in ('weightList','blendWeights') if copy_dq else ('weightList',):
        if check:check()
        root=ctx['fn'].findPlug(name,False)
        if root.isLocked or root.isDestination:raise ValueError('Target '+name+' is locked or driven.')
    # Query the sparse exceptions once in Maya, not every numerical weight plug
    # through Python. Parents and individual elements are included by -multi.
    if check:check()
    locked=cmds.listAttr(ctx['skin'],locked=True,multi=True,shortNames=False) or []
    for name in locked:
        if check:check()
        if name.startswith(ctx['skin']+'.'):name=name[len(ctx['skin'])+1:]
        if blocked_weight_channel(name,affected,copy_dq):raise ValueError('Target weight channel is locked: '+name)
    if check:check()
    for plug in ctx['fn'].getConnections():
        if check:check()
        if not plug.isDestination:continue
        name=plug.partialName(includeNonMandatoryIndices=True,includeInstancedIndices=True,useFullAttributePath=True,useLongNames=True)
        if blocked_weight_channel(name,affected,copy_dq):raise ValueError('Target weight channel has an incoming driver: '+name)


def plan(data,progress=False):
    with planning(progress,data.get('max_seconds',120),label='Build transfer plan') as monitor:return _plan(data,monitor)


def preview_transfer(data,progress=True):
    with planning(progress,data.get('max_seconds',120),label='Preview transfer') as monitor:return _plan(data,monitor,read_only=True)['summary']


def select_preview_vertices(data,progress=True):
    with planning(progress,data.get('max_seconds',120),label='Select preview vertices') as monitor:
        result=_plan(data,monitor,read_only=True);summary=result['summary']
        monitor.stage('Selecting preview vertices in Maya',99)
        selection=om.MSelectionList()
        if summary['changed_ids']:selection.add((result['ctx']['dag'],components(summary['changed_ids'])))
        om.MGlobal.selectCommand(selection,om.MGlobal.kReplaceList)
        return summary


def preview_key(data,source,target,mapped,src_mask,tgt_mask,src_dq,tgt_dq,cache,check,geometry=None):
    # Revalidate live scene values before reusing the small, read-only summary.
    def mesh_key(ctx):
        return (ctx['uuid'],ctx.get('skin_uuid'),ctx['topology'],ctx.get('sample_key'),
                tuple(r['uuid'] for r in ctx['influences']),cache.fingerprint(ctx['weights'],check=check))
    return ('preview',json.dumps(data,sort_keys=True,allow_nan=False),mesh_key(source),mesh_key(target),geometry,
            json.dumps(mapped['rows'],sort_keys=True,allow_nan=False),
            *(cache.fingerprint(values,check=check) if values is not None else None for values in (src_mask,tgt_mask,src_dq,tgt_dq)))


def _plan(data,monitor,read_only=False):
    cache=cache_service()
    monitor.stage('Reading source mesh and weights',0)
    source=context(data['source'],check=monitor.check)
    monitor.stage('Reading target mesh and weights',8)
    target=context(data['target'],check=monitor.check);method=data.get('method','surface')
    if method not in ('id','surface','region'):raise ValueError('Unknown copy method.')
    monitor.stage('Matching influences',16)
    mapped=mapping_report(data,source,target,check=monitor.check)
    if not mapped['complete']:raise ValueError('; '.join(mapped['errors']))
    validate_mapping_review(mapped,data.get('reviewed_mapping'))
    mapping=mapped['mapping']
    opacity=core.unit(data.get('opacity',1));src_mask=None;tgt_mask=None;source_faces=None;target_vertices=None
    if method=='region':
        source_faces=region(source,data.get('source_region'),True);target_vertices=region(target,data.get('target_region'))
        src_mask=mask_values(source,'source') if data.get('source_mask') else None
        tgt_mask=mask_values(target,'target') if data.get('target_mask') else None
        if source_faces is None and src_mask is None:raise ValueError('Method 3 requires source faces or a source mask.')
        if target_vertices is None and tgt_mask is None:raise ValueError('Method 3 requires target faces/vertices or a target mask.')
    vertices=sorted(target_vertices) if target_vertices is not None else list(range(target['count']))
    if method=='id':
        if source['count']!=target['count']:raise ValueError('Vertex-ID transfer requires equal vertex counts.')
        if data.get('verify_topology',True) and source['topology']!=target['topology']:raise ValueError('Vertex-ID topology differs. Verify vertex ordering before disabling topology verification.')
    else:
        mode=data.get('geometry','base')
        monitor.stage('Evaluating source geometry',22)
        src_points,triangles=sample_geometry(source,mode,data.get('source_base',''),check=monitor.check)
        monitor.stage('Evaluating target geometry',27)
        tgt_points,_=sample_geometry(target,mode,data.get('target_base',''),check=monitor.check)
        if source_faces is not None:triangles=[t for t in triangles if t[0] in source_faces]
        monitor.stage('Preparing source triangles and masks',32)
        surface_key=cache.surface_key(src_points,triangles,src_mask,
            float(data.get('mask_threshold',.001)),source.get('sample_key'),monitor.check)
    max_distance=float(data.get('max_distance',0))
    if not math.isfinite(max_distance) or max_distance<0:raise ValueError('Max distance must be nonnegative; zero means unlimited.')
    max_distance=om.MDistance(max_distance,om.MDistance.uiUnit()).asCentimeters()
    if method!='id':
        target_token=target.get('sample_key') or cache.geometry_token(('target',target['uuid']),target['topology'],tgt_points,())
    monitor.stage('Reading DQ weights',35)
    copy_dq=bool(data.get('copy_dq',False));src_dq=list(source['fn'].getBlendWeights(source['dag'],components(range(source['count'])))) if copy_dq else None
    tgt_dq=list(target['fn'].getBlendWeights(target['dag'],components(range(target['count'])))) if copy_dq else None
    key=None
    if read_only:
        geometry=(surface_key,target_token,max_distance) if method!='id' else None
        key=preview_key(data,source,target,mapped,src_mask,tgt_mask,src_dq,tgt_dq,cache,monitor.check,geometry)
        payload=cache.get(key)
        if payload is not None:
            summary=json.loads(payload);summary['preview_cache_reused']=True;summary['cache']=cache.stats()
            monitor.stage('Preview ready from validated cache',98)
            return {'ctx':target,'vertices':summary['changed_ids'],'before':[],'after':[],'before_dq':[],'after_dq':[],'copy_dq':copy_dq,'summary':summary}
    hits=None;hit_key=None;hit_cost=0;hits_cached=False
    if method!='id':
        monitor.stage('Building source surface index',40)
        index,record_count,degenerate,surface_key,surface_cached=cache.surface(core,src_points,triangles,src_mask,
            float(data.get('mask_threshold',.001)),source.get('sample_key'),monitor.check,key=surface_key)
        hit_key,hits,hits_cached,hit_cost=cache.correspondence(surface_key,target_token,vertices,max_distance,monitor.check)
    changed=[];before=[];after=[];before_dq=[];after_dq=[];missed=0;masked=0;maximum=0.;candidates=0;changed_count=0
    monitor.stage('Sampling target vertices',50)
    for number,v in enumerate(vertices):
        monitor.value=50+40*number/max(1,len(vertices));monitor.check()
        alpha=opacity*(tgt_mask[v] if tgt_mask is not None else 1.)
        if alpha<=1e-12:masked+=1;continue
        if method=='id':ids=(v,v,v);bary=(1.,0.,0.)
        else:
            hit=hits[number] if hits is not None else False
            if hit is False:
                found=index.nearest(tgt_points[v],max_distance,check=monitor.check);cache.queries+=1
                hit=(found['ids'],found['bary'],found['distance'],found['source_alpha']) if found is not None else None
                if hits is not None:hits[number]=hit
            else:cache.reused_queries+=1
            if hit is None:missed+=1;continue
            ids,bary,distance,source_alpha=hit;maximum=max(maximum,distance)
            alpha*=max(0.,min(1.,source_alpha))
        if alpha<=1e-12:masked+=1;continue
        sampled=core.interpolate(source['weights'],source['width'],ids,bary,mapping,target['width'])
        old=target['weights'][v*target['width']:(v+1)*target['width']]
        new=core.transfer_row(old,sampled,alpha);candidates+=1
        dq=(1-alpha)*tgt_dq[v]+alpha*sum(src_dq[j]*b for j,b in zip(ids,bary)) if copy_dq else None
        if not same(old,new,1e-12) or (copy_dq and abs(tgt_dq[v]-dq)>1e-12):
            changed_count+=1
            if not read_only or len(changed)<5000:changed.append(v)
            if not read_only:
                before.extend(old);after.extend(new)
                if copy_dq:before_dq.append(tgt_dq[v]);after_dq.append(dq)
    if not read_only:
        monitor.stage('Checking target locks and connections',92)
        writable(target,changed,after,copy_dq,check=monitor.check)
    monitor.stage('Preview calculation complete',98)
    if hits is not None:cache.put(hit_key,hits,hit_cost)
    result={'ctx':target,'vertices':changed,'before':before,'after':after,'before_dq':before_dq,'after_dq':after_dq,'copy_dq':copy_dq,
            'summary':{'method':method,'geometry':data.get('geometry','base') if method!='id' else 'vertex IDs',
                       'eligible_vertices':candidates,'changed_vertices':changed_count,'masked_vertices':masked,'distance_skips':missed,
                       'max_hit_distance_cm':maximum,'source_triangles':record_count if method!='id' else 0,
                       'degenerate_triangles_skipped':degenerate if method!='id' else 0,
                       'influence_mapping':[(r['path'],target['influences'][j]['path']) for r,j in zip(source['influences'],mapping)],
                       'mapping_details':mapped['rows'],
                       'cache':cache.stats(),'surface_cache_reused':surface_cached if method!='id' else False,
                       'correspondence_cache_reused':hits_cached,
                       'preview_cache_reused':False,'write_preflight':'deferred until Copy' if read_only else 'passed',
                       'changed_ids':changed[:5000],'changed_ids_truncated':changed_count>5000}}
    if read_only:
        payload=json.dumps(result['summary']);cache.put(key,payload,len(payload.encode('utf-8'))*2+2048)
    return result


class CopyCommand(om.MPxCommand):
    @staticmethod
    def creator():return CopyCommand()
    @staticmethod
    def syntax():
        result=om.MSyntax();result.addFlag('-d','-data',om.MSyntax.kString);return result
    def isUndoable(self):return getattr(self,'undoable',False)
    def doIt(self,args):
        if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Maya Undo before copying weights.')
        arguments=om.MArgDatabase(self.syntax(),args);data=json.loads(arguments.flagArgumentString('-data',0))
        operation=data.get('operation','copy')
        if operation not in ('copy','edit'):raise ValueError('Unknown Skinning Tools command operation.')
        if operation=='edit':
            with planning(True,label='Weight edit · '+data.get('action','edit')) as monitor:
                self._apply(edit_plan(data,progress=False,monitor=monitor),monitor)
            return
        with planning(True,data.get('max_seconds',120),label='Copy skinning') as monitor:
            self._apply(_plan(data,monitor),monitor)
    def _apply(self,result,monitor=None):
        self.result=result
        # Undo needs only the skin function set, DAG path and physical width.
        # Do not retain evaluated input mesh data or whole-mesh read buffers.
        self.result['ctx']={key:value for key,value in self.result['ctx'].items() if key in ('fn','dag','width')}
        self.component=components(self.result['vertices'])
        self.indices=om.MIntArray(range(self.result['ctx']['width']));self.undoable=bool(self.result['vertices'])
        if monitor:
            monitor.stage('Writing and verifying target weights in Maya',99)
            monitor.begin_write()
        # Native setWeights/verification is atomic from this UI's perspective.
        # Do not raise a late cancellation after a successful write.
        self.redoIt();self.setResult(json.dumps(self.result['summary']))
    def write(self,which):
        result=self.result
        if not result['vertices']:return
        ctx=result['ctx'];values=om.MDoubleArray(result[which])
        ctx['fn'].setWeights(ctx['dag'],self.component,self.indices,values,False)
        if result['copy_dq']:ctx['fn'].setBlendWeights(ctx['dag'],self.component,om.MDoubleArray(result[which+'_dq']))
        if not same(ctx['fn'].getWeights(ctx['dag'],self.component)[0],values,2e-6):raise RuntimeError('Maya changed requested weights.')
        if result['copy_dq'] and not same(ctx['fn'].getBlendWeights(ctx['dag'],self.component),result[which+'_dq'],2e-6):raise RuntimeError('Maya changed requested DQ blend weights.')
    def redoIt(self):
        try:self.write('after')
        except Exception:
            self.write('before');raise
    def undoIt(self):
        try:self.write('before')
        except Exception:
            self.write('after');raise


@contextmanager
def mask_undo():
    if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Undo before editing masks.')
    cmds.undoInfo(openChunk=True,chunkName='CopySkinMask')
    try:yield
    finally:cmds.undoInfo(closeChunk=True)


def mask_action(mesh,role,action,value=1.):
    ctx=context(mesh);name=MASKS[role];value=core.unit(value)
    if cmds.referenceQuery(ctx['shape'],isNodeReferenced=True) or om.MFnDependencyNode(ctx['dag'].node()).isLocked:raise ValueError('Mask mesh is referenced or locked.')
    if action=='selected':
        selected=capture_region(mesh,False)['vertices']
    elif action not in ('paint','black','white'):raise ValueError('Unknown mask action.')
    with mask_undo():
        if name not in ctx['mesh'].getColorSetNames():
            cmds.polyColorSet(ctx['shape'],create=True,colorSet=name,representation='RGB')
            cmds.polyColorSet(ctx['shape'],currentColorSet=True,colorSet=name)
            cmds.polyColorPerVertex(ctx['shape']+'.vtx[*]',rgb=(0,0,0))
        cmds.polyColorSet(ctx['shape'],currentColorSet=True,colorSet=name)
        cmds.setAttr(ctx['shape']+'.displayColors',True)
        if action in ('black','white','selected'):
            level=0. if action=='black' else 1. if action=='white' else value
            items=[ctx['shape']+'.vtx[{}]'.format(v) for v in selected] if action=='selected' else [ctx['shape']+'.vtx[*]']
            cmds.polyColorPerVertex(items,rgb=(level,level,level))
    if action=='paint':
        cmds.select(ctx['shape'],replace=True)
        tool='rtkCopySkinMaskPaint'
        if not cmds.artAttrPaintVertexCtx(tool,exists=True):cmds.artAttrPaintVertexCtx(tool)
        cmds.artAttrPaintVertexCtx(tool,edit=True,paintComponent=1,paintVertexFace=False,paintRGBA=False,
                                   paintChannel='RGB',colorRGBValue=(value,value,value),opacity=1.)
        cmds.setToolTo(tool)
    return name


def bind_target(source,target):
    src=context(source,read_weights=False);path=mesh_path(target)
    if cmds.ls(cmds.listHistory(path.fullPathName()) or [],type='skinCluster'):
        # Preparation must never unbind/recreate an existing skin or reset weights.
        return context(target,read_weights=False)['skin']
    for node in (path.fullPathName(),):
        if cmds.referenceQuery(node,isNodeReferenced=True) or om.MFnDependencyNode(path.node()).isLocked:raise ValueError('Target is referenced or locked.')
    if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Undo before binding.')
    return cmds.skinCluster([j['path'] for j in src['influences']],path.fullPathName(),toSelectedBones=True,
                            normalizeWeights=1,obeyMaxInfluences=False)[0]


def initializePlugin(plugin):
    fn=om.MFnPlugin(plugin,'RTK','0.4.3','Any')
    _load_core(fn.loadPath())
    fn.registerCommand(COMMAND,CopyCommand.creator,CopyCommand.syntax)
def uninitializePlugin(plugin):
    om.MFnPlugin(plugin).deregisterCommand(COMMAND)
    module=sys.modules.get('_rtk_copy_skin_cache_043')
    if module is not None:module.CACHE.clear()
