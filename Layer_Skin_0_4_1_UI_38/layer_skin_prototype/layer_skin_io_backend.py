"""Skin file capture/import and an extension of the registered 0.4.1 command.

Imports become a full-coverage top layer. The registered command class and its
existing Undo objects remain live; no plug-in unload or Undo reset is used.
"""
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import time
import uuid


def sibling(name):
    path=os.path.join(os.path.dirname(globals().get('__file__') or sibling.__code__.co_filename),name+'.py')
    spec=importlib.util.spec_from_file_location('_rtk_io9_'+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


io=sibling('layer_skin_io')


def owner_of(api):
    function=getattr(api.clear_cache,'__func__',api.clear_cache)
    return getattr(api,'_layer_skin_command_owner',getattr(function,'__globals__',{}))


def component(om,vertices):
    fn=om.MFnSingleIndexedComponent();value=fn.create(om.MFn.kMeshVertComponent);fn.addElements(vertices);return value


def writable(plug):
    if plug.isLocked or plug.isDestination:raise ValueError('Skin setting is locked or driven: '+plug.name())


class Auxiliary:
    """DQ/method snapshots retained by the same native layer Undo command."""
    def __init__(self,owner,ctx,payload):
        self.om=owner['om'];self.fn=ctx['fn'];self.dag=ctx['dag'];self.method=None;self.vertices=[];self.before=[];self.after=[];self.comp=None
        desired_method=payload.get('skinning_method')
        if desired_method is not None:
            if type(desired_method) is not int or desired_method not in (0,1,2):raise ValueError('Invalid imported skinning method.')
            plug=self.fn.findPlug('skinningMethod',False);before=plug.asInt()
            if before!=desired_method:writable(plug);self.method=(plug,before,desired_method)
        desired=payload.get('dq')
        if desired is not None:
            if len(desired)!=ctx['count'] or any(not math.isfinite(v) or not 0<=v<=1 for v in desired):raise ValueError('Invalid imported DQ values.')
            all_components=component(self.om,range(ctx['count']));current=list(self.fn.getBlendWeights(self.dag,all_components))
            if len(current)!=ctx['count']:raise ValueError('DQ component count changed.')
            self.vertices=[v for v,(a,b) in enumerate(zip(current,desired)) if abs(a-b)>1e-12]
            if self.vertices:
                self._check_dq(ctx['skin']);self.comp=component(self.om,self.vertices)
                self.before=[current[v] for v in self.vertices];self.after=[desired[v] for v in self.vertices]
        if (self.method or self.vertices) and getattr(self.fn,'isLocked',False):raise ValueError('The skinCluster is locked.')
        self.skin=ctx['skin']
    def _check_dq(self,skin):
        plug=self.fn.findPlug('blendWeights',False);writable(plug)
        changed=set(self.vertices)
        for index in plug.getExistingArrayAttributeIndices():
            if index in changed:writable(plug.elementByLogicalIndex(index))
    def write(self,after):
        if self.method:
            plug,before,desired=self.method;writable(plug);plug.setInt(desired if after else before)
            if plug.asInt()!=(desired if after else before):raise RuntimeError('Maya did not retain the imported skinning method.')
        if self.vertices:
            self._check_dq(self.skin);values=self.after if after else self.before
            self.fn.setBlendWeights(self.dag,self.comp,self.om.MDoubleArray(values))
            actual=list(self.fn.getBlendWeights(self.dag,self.comp))
            if len(actual)!=len(values) or any(abs(a-b)>2e-6 for a,b in zip(actual,values)):
                raise RuntimeError('Maya changed the imported DQ blend weights.')


class Runtime:
    def __init__(self,owner):self.owner=owner;self.pending={}
    def register(self,payload):
        token=uuid.uuid4().hex;self.pending[token]=payload;return token
    def discard(self,token):self.pending.pop(token,None)


class SkinFunction:
    """Forward the native function set and retain this command's auxiliary Undo.

    LayerCommand keeps ctx['fn'] in its own snapshot. This avoids changing any
    MPxCommand virtual method or relying on Maya to rediscover virtual overrides.
    """
    def __init__(self,source,auxiliary):self.source=source;self._skin_io_auxiliary=auxiliary
    def __getattr__(self,name):return getattr(self.source,name)


def install(owner):
    """Wrap planner/write without replacing or re-registering MPxCommand."""
    cls=owner.get('LayerCommand');previous=owner.get('prepare_edit')
    if cls is None or not callable(previous):return None
    runtime=owner.get('_skin_io_runtime')
    if runtime is not None and getattr(previous,'_skin_io_runtime',None) is runtime:return runtime
    runtime=Runtime(owner)
    original=getattr(previous,'_layer_skin_io_original',previous)
    original_write=getattr(cls.write,'_layer_skin_io_original',cls.write)
    def write(command,values):
        original_write(command,values)
        auxiliary=getattr(command,'_skin_io_auxiliary',None) or getattr(command.ctx['fn'],'_skin_io_auxiliary',None)
        if auxiliary is not None:auxiliary.write(values is command.after)
    def prepare(ctx,meta,state,action,data):
        if action!='import_skin':return original(ctx,meta,state,action,data)
        payload=runtime.pending.pop(data.get('io_token'),None)
        if payload is None:raise ValueError('The skin import plan expired. Preview the file again.')
        if payload['target_uuid']!=ctx.get('uuid') or payload['topology']!=ctx['topology'] or payload['count']!=ctx['count']:
            raise ValueError('The target mesh changed. Preview skin import again.')
        blank,_,_=original(ctx,meta,state,'add',dict(name=payload.get('name') or 'Imported skin',expected=data.get('expected')))
        result=io.import_state(owner['core'],blank,ctx,payload,added=True)
        if payload.get('dq') is not None or payload.get('skinning_method') is not None:
            ctx['fn']=SkinFunction(ctx['fn'],Auxiliary(owner,ctx,payload))
        return result,list(range(ctx['count'])),False
    write._layer_skin_io_original=original_write
    prepare._layer_skin_io_original=original;prepare._skin_io_runtime=runtime
    # Let a later Relax refresh unwrap the complete extension chain once.
    prepare._layer_skin_relax_original=getattr(original,'_layer_skin_relax_original',original)
    cls.write=write;owner['prepare_edit']=prepare;owner['_skin_io_runtime']=runtime
    return runtime


@contextlib.contextmanager
def computation():
    import maya.OpenMaya as legacy
    monitor=legacy.MComputation();monitor.beginComputation(False,True,False);started=time.monotonic()
    try:
        def check():
            if monitor.isInterruptRequested():raise RuntimeError('Skin file operation cancelled.')
            if time.monotonic()-started>600.:raise RuntimeError('Skin file operation exceeded 600 seconds; no further writes were made.')
        yield check
    finally:monitor.endComputation()


class Backend:
    def __init__(self,api):self.api=api;self.owner=owner_of(api);self.runtime=install(self.owner)
    @contextlib.contextmanager
    def computation(self):
        previous=self.owner.get('_layer_skin_io_check')
        with computation() as check:
            self.owner['_layer_skin_io_check']=check
            try:yield check
            finally:
                if previous is None:self.owner.pop('_layer_skin_io_check',None)
                else:self.owner['_layer_skin_io_check']=previous
    def mesh(self,target,read_weights=True):
        api=self.api;cmds=api.cmds;om=api.om
        names=list(dict.fromkeys(cmds.ls(target,long=True,objectsOnly=True) or [])) if target else []
        if len(names)!=1:raise ValueError('Get one polygon mesh.')
        name=names[0]
        shapes=[name] if cmds.nodeType(name)=='mesh' else [p for p in cmds.listRelatives(name,shapes=True,noIntermediate=True,fullPath=True) or [] if cmds.nodeType(p)=='mesh']
        if len(shapes)!=1:raise ValueError('Choose a transform with one polygon mesh.')
        selection=om.MSelectionList();selection.add(shapes[0]);dag=selection.getDagPath(0)
        if dag.isInstanced():raise ValueError('Instanced meshes are outside the Layer Skin prototype.')
        history=cmds.listHistory(shapes[0],pruneDagObjects=True) or []
        skins=list(dict.fromkeys(cmds.ls(history,type='skinCluster') or [])) if history else []
        if len(skins)>1:raise ValueError('Multiple skinClusters are outside this prototype.')
        if skins and read_weights:return api.context(shapes[0])
        if skins:return dict(shape=dag.fullPathName(),skin=skins[0])
        return dict(shape=dag.fullPathName(),dag=dag,mesh=om.MFnMesh(dag),skin=None,fn=None,ids=[],weights=[],influences=[],
            count=om.MFnMesh(dag).numVertices,uuid=om.MFnDependencyNode(dag.node()).uuid().asString())
    def geometry(self,ctx,mode='base'):
        om=self.api.om;fn=ctx['mesh']
        if ctx['skin'] and mode=='base':
            index=ctx['fn'].indexForOutputShape(ctx['dag'].node());plug=ctx['fn'].findPlug('input',False).elementByLogicalIndex(index)
            value=next(plug.child(i) for i in range(plug.numChildren()) if om.MFnAttribute(plug.child(i).attribute()).name=='inputGeometry').asMObject();fn=om.MFnMesh(value)
        counts,indices=fn.getVertices();signature=io.topology(fn.numVertices,counts,indices)
        points=[tuple(p)[:3] for p in fn.getPoints(om.MSpace.kObject)]
        tri_counts,tri_ids=fn.getTriangles();triangles=[tuple(tri_ids[i:i+3]) for i in range(0,len(tri_ids),3)]
        return dict(points=points,triangles=triangles,topology=signature,count=fn.numVertices)
    def influence_records(self,ctx):
        api=self.api;result=[]
        for path in ctx['influences']:
            name=path.fullPathName();identity=api.om.MFnDependencyNode(path.node()).uuid().asString()
            try:index=ctx['fn'].indexForInfluenceObject(path)
            except TypeError:index=ctx['fn'].indexForInfluenceObject(path.node())
            raw=api.cmds.getAttr(ctx['skin']+'.bindPreMatrix[{}]'.format(index))
            if len(raw)==1 and isinstance(raw[0],(list,tuple)):raw=raw[0]
            matrix=api.om.MMatrix(raw)
            if matrix.isSingular():raise ValueError('Invalid bind matrix: '+name)
            result.append(dict(uuid=identity,path=name,position=list(matrix.inverse())[12:15],bind_pre_matrix=list(raw)))
        return result
    def candidates(self,ctx,root='',check=None):
        api=self.api;records=self.influence_records(ctx) if ctx['skin'] else [];known={r['uuid'] for r in records}
        if root:
            roots=api.cmds.ls(root,long=True,objectsOnly=True) or []
            if len(roots)!=1:raise ValueError('Choose one joint hierarchy root.')
            names=[roots[0]]+(api.cmds.listRelatives(roots[0],allDescendents=True,type='joint',fullPath=True) or [])
            scope=set(names);records=[r for r in records if r['path'] in scope];known={r['uuid'] for r in records}
        else:names=api.cmds.ls(type='joint',long=True) or []
        for i,name in enumerate(names):
            if check and i%32==0:check()
            if api.cmds.nodeType(name) not in ('joint','transform'):continue
            selection=api.om.MSelectionList();selection.add(name);path=selection.getDagPath(0)
            identity=api.om.MFnDependencyNode(path.node()).uuid().asString()
            if identity not in known:records.append(dict(uuid=identity,path=path.fullPathName(),position=list(path.inclusiveMatrix())[12:15]));known.add(identity)
        if len(records)>4096:raise ValueError('More than 4,096 candidate joints. Choose a joint hierarchy root.')
        return records
    def selected_mesh(self):
        names=self.api.cmds.ls(selection=True,long=True,objectsOnly=True) or []
        if len(names)!=1:raise ValueError('Select one mesh in Maya.')
        return self.mesh(names[0],read_weights=False)['shape']
    def selected_joint(self):
        names=self.api.cmds.ls(selection=True,long=True,objectsOnly=True) or []
        if len(names)!=1 or self.api.cmds.nodeType(names[0]) not in ('joint','transform'):raise ValueError('Select one joint or transform influence.')
        return names[0]
    def record_for_path(self,ctx,path):
        names=self.api.cmds.ls(path,long=True,objectsOnly=True) or []
        if len(names)!=1 or self.api.cmds.nodeType(names[0]) not in ('joint','transform'):raise ValueError('Manual influence no longer exists.')
        selection=self.api.om.MSelectionList();selection.add(names[0]);dag=selection.getDagPath(0)
        identity=self.api.om.MFnDependencyNode(dag.node()).uuid().asString()
        for record in self.influence_records(ctx) if ctx['skin'] else []:
            if record['uuid']==identity:return record
        return dict(uuid=identity,path=dag.fullPathName(),position=list(dag.inclusiveMatrix())[12:15])
    def capture(self,target,geometry='base',include_geometry=True,check=None):
        ctx=self.mesh(target)
        if not ctx['skin']:raise ValueError('Export requires a skinned mesh.')
        if check:check()
        shape=self.geometry(ctx,geometry) if include_geometry else dict(topology=ctx['topology']);n=ctx['count']
        snapshot=dict(count=n,topology=shape['topology'],weights=ctx['weights'],influences=self.influence_records(ctx),
            skinning_method=int(self.api.cmds.getAttr(ctx['skin']+'.skinningMethod')),
            dq=list(ctx['fn'].getBlendWeights(ctx['dag'],component(self.api.om,range(n)))),geometry=geometry,
            world_matrix=list(ctx['dag'].inclusiveMatrix()),mesh=ctx['shape'],mesh_uuid=ctx['uuid'])
        if include_geometry:snapshot.update(points=shape['points'],triangles=shape['triangles'])
        return io.validate(snapshot,check)
    def export(self,target,path,geometry='base',include_geometry=True,overwrite=False):
        with self.computation() as check:return io.write(path,self.capture(target,geometry,include_geometry,check),overwrite,check)
    def fingerprint(self,ctx,geometry):
        state=None;meta=None
        if ctx['skin']:meta,state=self.api.metadata(ctx)
        if state is not None and not self.api.same(ctx['weights'],self.api.core.composite(state),2e-6):
            raise ValueError('Native weights differ from saved layers. Undo outside edits or use Cleanup before importing.')
        if state is not None and len(state['layers'])>=self.api.core.MAX_LAYERS:raise ValueError('The layer limit is reached. Remove a layer before importing.')
        point_hash=hashlib.sha256(io.binary((x for point in geometry['points'] for x in point),'d')).hexdigest()
        weights_hash=io.storage().digest_values(ctx['weights'])
        dq_hash=hashlib.sha256(io.binary(ctx['fn'].getBlendWeights(ctx['dag'],component(self.api.om,range(ctx['count']))),'d')).hexdigest() if ctx['skin'] else None
        return io.digest(dict(mesh=ctx['uuid'],skin=ctx['skin'],ids=ctx['ids'],weights=weights_hash,
            skin_uuid=self.api.om.MFnDependencyNode(self.api.obj(ctx['skin'])).uuid().asString() if ctx['skin'] else None,
            dq=dq_hash,skinning_method=int(self.api.cmds.getAttr(ctx['skin']+'.skinningMethod')) if ctx['skin'] else None,
            state=(ctx.get('raw_metadata') or self.api.core.encode(state)) if state else None,
            geometry=dict(count=geometry['count'],topology=geometry['topology'],points=point_hash)))
    def candidate_signature(self,records,required):
        return io.digest(sorted((r['uuid'],r.get('position'),r.get('bind_pre_matrix')) for r in records if r['uuid'] in required))
    def preview(self,snapshot,target,options=None,manual=None,root='',method='id',geometry='base',max_distance=0.,copy_dq=True,copy_method=True,name='Imported skin',manual_paths=None):
        options=dict(options or {})
        with self.computation() as check:
            ctx=self.mesh(target);shape=self.geometry(ctx,geometry);check()
            candidates=self.candidates(ctx,root,check);options['tolerance']=self.api.om.MDistance(options.get('tolerance',.01),self.api.om.MDistance.uiUnit()).asCentimeters()
            known={r['uuid'] for r in candidates}
            if manual_paths:
                for identity,path in manual_paths.items():
                    record=self.record_for_path(ctx,path)
                    if identity!=record['uuid']:raise ValueError('A manual joint selection changed. Choose it again.')
                    if identity not in known:candidates.append(record);known.add(identity)
            report=io.map_joints(snapshot,candidates,options,manual,check)
            converted=io.project(snapshot,shape,method,self.api.om.MDistance(max_distance,self.api.om.MDistance.uiUnit()).asCentimeters(),check)
            full_map={row['source_uuid']:row['target_uuid'] for row in report['rows']}
            mapped=[full_map.get(r['uuid']) for r in snapshot['influences']]
            target_ids=set(ctx['ids'])|{value for value in mapped if value is not None}
            if target_ids:io.storage().dimensions(ctx['count'],len(target_ids))
            fingerprint=self.fingerprint(ctx,shape)
            payload=dict(source_ids=[r['uuid'] for r in snapshot['influences']],mapping=mapped,weights=converted['weights'],
                dq=converted['dq'] if copy_dq else None,skinning_method=snapshot.get('skinning_method',0) if copy_method else None,
                name=name.strip() or 'Imported skin',count=ctx['count'],topology=ctx.get('topology',shape['topology']),target_uuid=ctx['uuid'])
            return dict(target=ctx['shape'],target_uuid=ctx['uuid'],fingerprint=fingerprint,geometry=geometry,
                shape=shape,report=report,payload=payload,candidates=candidates,missing=[r['path'] for r in candidates if r['uuid'] in target_ids-set(ctx['ids'])],
                target_handle=self.api.om.MObjectHandle(ctx['dag'].node()),target_paths={r['uuid']:r['path'] for r in candidates},
                candidate_signature=self.candidate_signature(candidates,target_ids),max_distance=converted['max_distance'],method=method,skin=ctx['skin'])
    def commit(self,plan,create_skin=True,add_influences=True):
        if self.runtime is None:raise RuntimeError('Refresh the complete UI 9 folder before importing skin files.')
        if not plan['report']['complete']:raise ValueError('Resolve every weighted influence before Import.')
        if not self.api.cmds.undoInfo(query=True,state=True):raise ValueError('Enable Maya Undo before importing.')
        with self.computation() as check:
            if not plan['target_handle'].isValid() or not plan['target_handle'].isAlive():raise ValueError('The target scene changed. Preview skin import again.')
            ctx=self.mesh(plan['target']);shape=self.geometry(ctx,plan['geometry'])
            if self.fingerprint(ctx,shape)!=plan['fingerprint']:raise ValueError('Target skin, layers or geometry changed after Preview. Preview again before importing.')
            required={v for v in plan['payload']['mapping'] if v is not None}
            records=self.candidates(ctx);known={r['uuid'] for r in records}
            for identity in required-known:
                paths=self.api.cmds.ls(identity,long=True) or []
                if len(paths)==1:records.append(self.record_for_path(ctx,paths[0]))
            ids={r['uuid']:r['path'] for r in records}
            if any(identity not in ids for identity in required):raise ValueError('A mapped influence was removed. Preview again.')
            if self.candidate_signature(records,required|set(ctx['ids']))!=plan['candidate_signature']:raise ValueError('Mapped joint bind data or an unbound joint pose changed after Preview. Preview again.')
            if not ctx['skin'] and not create_skin:raise ValueError('Target has no skinCluster. Enable Create skinCluster if missing.')
            missing=[ids[v] for v in sorted(required) if v not in ctx['ids']]
            if ctx['skin'] and missing and not add_influences:raise ValueError('Mapped joints are not bound. Enable Add missing mapped influences.')
            io.storage().dimensions(ctx['count'],len(required|set(ctx['ids'])))
            meta,state=self.api.metadata(ctx) if ctx['skin'] else (None,None)
            self.owner['preflight'](ctx,meta,ctx['weights'],ctx['weights'],[])
            for path in missing:
                if self.api.cmds.attributeQuery('lockInfluenceWeights',node=path,exists=True) and self.api.cmds.getAttr(path+'.lockInfluenceWeights'):
                    raise ValueError('A mapped influence is locked: '+path)
            check()
        cmds=self.api.cmds;chunk='LayerSkinImport_'+uuid.uuid4().hex;token=None;failure=None;cmds.undoInfo(openChunk=True,chunkName=chunk)
        try:
            if not ctx['skin']:
                cmds.skinCluster([ids[v] for v in sorted(required)],ctx['shape'],toSelectedBones=True,normalizeWeights=1,obeyMaxInfluences=False)
            else:
                for path in missing:cmds.skinCluster(ctx['skin'],edit=True,addInfluence=path,weight=0.)
            fresh=self.api.context(ctx['shape']);meta,state=self.api.metadata(fresh)
            payload=dict(plan['payload'],topology=fresh['topology']);token=self.runtime.register(payload)
            data=dict(target=fresh['shape'],io_token=token)
            if state is not None:data['expected']=hashlib.sha256(self.api.core.encode(state).encode()).hexdigest()
            result=cmds.rtkLayerSkin(action='import_skin',data=json.dumps(data))
            verified=self.api.context(fresh['shape']);_,saved=self.api.metadata(verified)
            io.verify_import(self.api.core,state,saved,verified,payload)
        except Exception as exc:failure=exc
        finally:
            cmds.undoInfo(closeChunk=True)
            if token:self.runtime.discard(token)
        if failure:
            if cmds.undoInfo(query=True,undoName=True)==chunk:cmds.undo()
            raise failure
        return result or 'Skin file imported as a new top layer.'
