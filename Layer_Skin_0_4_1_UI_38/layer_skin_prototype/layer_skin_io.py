"""Versioned .rtkskin archives and transfer planning. No Maya or Qt imports."""
import array
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import zipfile

def storage():
    key='_rtk_layer_skin_storage_20'
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,os.path.join(os.path.dirname(__file__),'layer_skin_storage.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[key]=module
    return sys.modules[key]


FORMAT='rtkSkin';VERSION=1;MAX_VALUES=storage().MAX_VALUES;MAX_BYTES=storage().MAX_ARCHIVE_BYTES
MAX_TRIANGLES=4_000_000;TOL=1e-6
_transfer=None


def transfer():
    global _transfer
    if _transfer is None:
        path=os.path.join(os.path.dirname(globals().get('__file__') or transfer.__code__.co_filename),'layer_skin_transfer.py')
        spec=importlib.util.spec_from_file_location('_rtk_layer_skin_transfer_9',path)
        _transfer=importlib.util.module_from_spec(spec);spec.loader.exec_module(_transfer)
    return _transfer


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def binary(values,kind):
    result=array.array(kind,values)
    if sys.byteorder!='little':result.byteswap()
    return result.tobytes()


def topology(count,counts,indices):
    h=hashlib.sha256(str(count).encode('ascii'));h.update(binary(counts,'q'));h.update(binary(indices,'q'));return h.hexdigest()


def _finite(values):return all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in values)
def _int(value):return type(value) is int
def _check(check,index):
    if check and index%256==0:check()


def validate(snapshot,check=None):
    n=snapshot.get('count');infs=snapshot.get('influences',[]);k=len(infs)
    storage().dimensions(n,k)
    if n*k>MAX_VALUES:raise ValueError('Skin file exceeds the packed-buffer budget.')
    ids=[]
    for record in infs:
        if not isinstance(record,dict):raise ValueError('Invalid influence record.')
        if any(not isinstance(record.get(key),str) or not record[key] or len(record[key])>4096 for key in ('uuid','path')):raise ValueError('Invalid influence name or UUID.')
        ids.append(record['uuid']);position=record.get('position')
        if position is not None and (len(position)!=3 or not _finite(position)):raise ValueError('Invalid bind influence position.')
        matrix=record.get('bind_pre_matrix')
        if matrix is not None and (len(matrix)!=16 or not _finite(matrix)):raise ValueError('Invalid bind matrix.')
    if len(set(ids))!=k:raise ValueError('Duplicate influence UUIDs in skin file.')
    values=snapshot.get('weights',[])
    if len(values)!=n*k:raise ValueError('Weight array size does not match the mesh.')
    if getattr(values,'_rtk_sparse_matrix',False) and (values.count!=n or values.width!=k):raise ValueError('Sparse matrix dimensions changed.')
    for v in range(n):
        _check(check,v)
        if getattr(values,'_rtk_sparse_matrix',False):
            start,end=values.offsets[v:v+2]
            if not 0<=start<=end<=len(values.values):raise ValueError('Sparse offsets are not monotonic.')
            pairs=list(values.entries(v));columns=[column for column,value in pairs]
            if any(not 0<=col<k for col in columns) or columns!=sorted(set(columns)):raise ValueError('Invalid sparse columns.')
            row=[value for column,value in pairs]
        else:row=values[v*k:(v+1)*k]
        if not _finite(row) or any(w<0 or w>1+TOL for w in row) or abs(math.fsum(row)-1.)>TOL:
            raise ValueError('Weights must be finite, nonnegative and normalized; vertex {} is invalid.'.format(v))
    signature=snapshot.get('topology')
    if not isinstance(signature,str) or len(signature)!=64 or any(c not in '0123456789abcdef' for c in signature):raise ValueError('Invalid topology fingerprint.')
    points=snapshot.get('points');triangles=snapshot.get('triangles')
    if (points is None)!=(triangles is None):raise ValueError('Geometry needs both points and triangles.')
    if points is not None:
        if len(points)!=n or any(len(p)!=3 or not _finite(p) for p in points):raise ValueError('Invalid saved mesh points.')
        if not 0<len(triangles)<=MAX_TRIANGLES or any(len(t)!=3 or any(not _int(v) or not 0<=v<n for v in t) for t in triangles):raise ValueError('Invalid saved triangles.')
    dq=snapshot.get('dq')
    if dq is not None and (len(dq)!=n or not _finite(dq) or any(not 0<=w<=1 for w in dq)):raise ValueError('Invalid DQ blend weights.')
    method=snapshot.get('skinning_method',0)
    if not _int(method) or method not in (0,1,2):raise ValueError('Invalid skinning method.')
    matrix=snapshot.get('world_matrix')
    if matrix is not None and (len(matrix)!=16 or not _finite(matrix)):raise ValueError('Invalid mesh world matrix.')
    if snapshot.get('geometry','base') not in ('base','current'):raise ValueError('Invalid geometry mode.')
    return snapshot


def used_columns(snapshot):
    weights=snapshot['weights']
    if getattr(weights,'_rtk_sparse_matrix',False):return {col for col,value in zip(weights.columns,weights.values) if value>0}
    k=len(snapshot['influences']);return {i%k for i,w in enumerate(weights) if w>0}


def write(path,snapshot,overwrite=False,check=None):
    """Stream lossless sparse arrays to an atomically replaced v1 archive."""
    validate(snapshot,check);path=os.path.abspath(os.fspath(path))
    if os.path.exists(path) and not overwrite:raise FileExistsError(path)
    if not os.path.isdir(os.path.dirname(path)):raise ValueError('Export directory does not exist.')
    n=snapshot['count'];k=len(snapshot['influences']);source=snapshot['weights']
    if getattr(source,'_rtk_sparse_matrix',False):
        offsets,columns,weights=source.offsets,source.columns,source.values
    else:
        offsets=array.array('Q',[0]);columns=array.array('I');weights=array.array('d')
        for v in range(n):
            _check(check,v)
            for j,value in storage().row_entries(source,v,k):columns.append(j);weights.append(value)
            offsets.append(len(weights))
    arrays={'row_offsets':('Q',offsets),'columns':('I',columns),'weights':('d',weights)}
    if snapshot.get('points') is not None:
        arrays['points']=('d',array.array('d',(x for p in snapshot['points'] for x in p)))
        arrays['triangles']=('I',array.array('I',(i for t in snapshot['triangles'] for i in t)))
    if snapshot.get('dq') is not None:arrays['dq']=('d',array.array('d',snapshot['dq']))
    manifest={key:snapshot[key] for key in ('count','topology','influences','skinning_method','geometry','world_matrix','mesh','mesh_uuid') if key in snapshot}
    manifest.update(format=FORMAT,version=VERSION,linear_unit='cm',point_space='mesh object',arrays={})
    if sum(len(values)*values.itemsize for kind,values in arrays.values())>MAX_BYTES:
        raise ValueError('Uncompressed skin archive exceeds the 1024 MiB size limit.')
    fd,temp=tempfile.mkstemp(prefix='.rtkskin_',suffix='.tmp',dir=os.path.dirname(path));os.close(fd)
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
            for name,(kind,values) in arrays.items():
                digest=hashlib.sha256()
                with z.open(name+'.bin','w',force_zip64=True) as member:
                    for block in storage().chunks(values,kind):
                        if check:check()
                        digest.update(block);member.write(block)
                manifest['arrays'][name]=dict(type=kind,count=len(values),sha256=digest.hexdigest())
            metadata=json.dumps(manifest,separators=(',',':'),allow_nan=False).encode()
            if len(metadata)>1024*1024:raise ValueError('Skin-file metadata exceeds 1 MiB.')
            if sum(len(v)*v.itemsize for _,v in arrays.values())+len(metadata)>MAX_BYTES:raise ValueError('Skin archive exceeds the size limit.')
            z.writestr('manifest.json',metadata)
        with open(temp,'rb+') as f:os.fsync(f.fileno())
        if check:check()
        if not overwrite and os.path.exists(path):raise FileExistsError(path)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.remove(temp)
    return dict(path=path,vertices=n,influences=k,nonzero=len(columns),bytes=os.path.getsize(path))


def read(path,check=None):
    """Validate and stream v1 arrays; large files remain CSR instead of dense."""
    with zipfile.ZipFile(os.fspath(path)) as z:
        info=z.infolist();names=[entry.filename for entry in info]
        if len(names)!=len(set(names)) or 'manifest.json' not in names:raise ValueError('Missing or duplicate skin archive members.')
        if sum(entry.file_size for entry in info)>MAX_BYTES or z.getinfo('manifest.json').file_size>1024*1024:raise ValueError('Skin archive exceeds the size limit.')
        manifest=json.loads(z.read('manifest.json').decode('utf-8'))
        if manifest.get('format')!=FORMAT or type(manifest.get('version')) is not int or manifest['version']!=VERSION:raise ValueError('Unsupported skin-file format/version.')
        n=manifest.get('count');infs=manifest.get('influences',[]);k=len(infs)
        storage().dimensions(n,k)
        if n*k>MAX_VALUES:raise ValueError('Skin file exceeds the packed-buffer budget.')
        descriptors=manifest.get('arrays',{});required={'row_offsets':'Q','columns':'I','weights':'d'};optional={'points':'d','triangles':'I','dq':'d'}
        if not isinstance(descriptors,dict) or not required.keys()<=descriptors.keys() or set(descriptors)-required.keys()-optional.keys():raise ValueError('Invalid skin-file arrays.')
        if set(names)!={'manifest.json'}|{name+'.bin' for name in descriptors}:raise ValueError('Unexpected skin archive members.')
        arrays={}
        for name,descriptor in descriptors.items():
            kind=(required|optional)[name];count=descriptor.get('count')
            if descriptor.get('type')!=kind or not _int(count) or count<0:raise ValueError('Invalid array type/count.')
            if z.getinfo(name+'.bin').file_size!=count*array.array(kind).itemsize:raise ValueError('Binary array size mismatch.')
            if name=='row_offsets' and count!=n+1:raise ValueError('Invalid sparse row offsets.')
            if name in ('columns','weights') and count>n*k:raise ValueError('Excessive sparse weight count.')
            if name=='points' and count!=n*3:raise ValueError('Invalid geometry arrays.')
            if name=='triangles' and (count%3 or count>MAX_TRIANGLES*3):raise ValueError('Invalid geometry arrays.')
            if name=='dq' and count!=n:raise ValueError('Invalid DQ blend weights.')
            values=array.array(kind);digest=hashlib.sha256()
            with z.open(name+'.bin') as member:
                while True:
                    if check:check()
                    block=member.read(storage().CHUNK_BYTES)
                    if not block:break
                    digest.update(block);values.frombytes(block)
            if len(values)!=count:raise ValueError('Binary array size mismatch.')
            if digest.hexdigest()!=descriptor.get('sha256'):raise ValueError('Skin-file checksum mismatch: '+name)
            if sys.byteorder!='little':values.byteswap()
            arrays[name]=values
    offsets=arrays['row_offsets'];columns=arrays['columns'];stored=arrays['weights']
    matrix=storage().SparseMatrix(n,k,offsets,columns,stored)
    for v in range(n):
        _check(check,v);start,end=offsets[v:v+2]
        if not 0<=start<=end<=len(stored):raise ValueError('Sparse offsets are not monotonic.')
        rowcols=columns[start:end]
        if any(not 0<=j<k for j in rowcols) or list(rowcols)!=sorted(set(rowcols)):raise ValueError('Sparse columns are invalid or duplicated.')
    if n*k>storage().PACK_THRESHOLD:dense=matrix
    else:
        dense=[0.]*(n*k)
        for v in range(n):
            for col,value in matrix.entries(v):dense[v*k+col]=value
    result={key:value for key,value in manifest.items() if key not in ('arrays','format','version','linear_unit','point_space')};result['weights']=dense
    if 'points' in arrays or 'triangles' in arrays:
        if 'points' not in arrays or 'triangles' not in arrays:raise ValueError('Invalid geometry arrays.')
        result['points']=[tuple(arrays['points'][i:i+3]) for i in range(0,len(arrays['points']),3)]
        result['triangles']=[tuple(arrays['triangles'][i:i+3]) for i in range(0,len(arrays['triangles']),3)]
    if 'dq' in arrays:result['dq']=list(arrays['dq'])
    if manifest.get('linear_unit')!='cm' or manifest.get('point_space')!='mesh object':raise ValueError('Unsupported saved geometry space/units.')
    return validate(result,check)



def map_joints(snapshot,candidates,options=None,manual=None,check=None):
    options=options or {};used=used_columns(snapshot);source=[r for i,r in enumerate(snapshot['influences']) if i in used]
    return transfer().resolve_influences(source,candidates,use_name=options.get('name',True),use_distance=options.get('distance',True),
        tolerance=options.get('tolerance',.01),max_edits=options.get('max_edits',3),search=options.get('search',''),replace=options.get('replace',''),
        ignore_namespace=options.get('ignore_namespace',True),manual=manual,check=check)


def project(snapshot,target,method='id',max_distance=0.,check=None):
    """Weights in source-column order; mesh-object cm space for spatial transfer."""
    validate(snapshot,check);n=target['count'];k=len(snapshot['influences'])
    storage().dimensions(n,k)
    if n*k>MAX_VALUES:raise ValueError('Transfer exceeds the packed-buffer budget.')
    if method=='id':
        if n!=snapshot['count'] or target['topology']!=snapshot['topology']:raise ValueError('Vertex ID import requires identical vertex count and topology. Use Closest surface for a different mesh.')
        source=snapshot['weights']
        values=source if getattr(source,'_rtk_sparse_matrix',False) else storage().copy_values(source)
        return dict(weights=values,dq=list(snapshot['dq']) if snapshot.get('dq') is not None else None,max_distance=0.)
    if method!='surface':raise ValueError('Unknown skin import method.')
    max_distance=float(max_distance)
    if not math.isfinite(max_distance) or max_distance<0:raise ValueError('Maximum surface distance must be nonnegative.')
    if snapshot.get('points') is None:raise ValueError('This file has no saved surface. Export again with Include transfer geometry.')
    points=target.get('points',[])
    if len(points)!=n or any(len(p)!=3 or not _finite(p) for p in points):raise ValueError('Invalid target transfer points.')
    math_module=transfer();triangles=[(i,t) for i,t in enumerate(snapshot['triangles'])]
    records,_=math_module.prepare_triangles(snapshot['points'],triangles,check=check);index=math_module.SurfaceIndex(records,check=check)
    large=n*k>storage().PACK_THRESHOLD
    offsets=array.array('Q',[0]);columns=array.array('I');sparse=array.array('d')
    weights=[];dq=[] if snapshot.get('dq') is not None else None;furthest=0.
    for v,p in enumerate(points):
        _check(check,v);hit=index.nearest(p,max_distance,check=check)
        if hit is None:raise ValueError('Target vertex {} has no surface within the maximum distance. No skin changes were made.'.format(v))
        bary=[max(0.,min(1.,x)) for x in hit['bary']];total=math.fsum(bary);bary=[x/total for x in bary]
        if large:
            values={}
            for vertex,factor in zip(hit['ids'],bary):
                for col,value in storage().row_entries(snapshot['weights'],vertex,k):values[col]=values.get(col,0.)+factor*value
            total=math.fsum(values.values())
            if total<=0:raise ValueError('Projected skin row has no weight.')
            for col,value in sorted(values.items()):
                if value>0:columns.append(col);sparse.append(value/total)
            offsets.append(len(sparse))
        else:
            row=[math.fsum(snapshot['weights'][vertex*k+j]*b for vertex,b in zip(hit['ids'],bary)) for j in range(k)]
            weights.extend(math_module.normalize(row))
        furthest=max(furthest,hit['distance'])
        if dq is not None:dq.append(max(0.,min(1.,math.fsum(snapshot['dq'][vertex]*b for vertex,b in zip(hit['ids'],bary)))))
    if large:weights=storage().SparseMatrix(n,k,offsets,columns,sparse)
    return dict(weights=weights,dq=dq,max_distance=furthest)


def import_state(core,state,ctx,payload,added=False):
    """Build a new full-coverage layer, leaving all previous authoring rows intact."""
    source=payload['source_ids'];mapped=payload['mapping'];weights=payload['weights'];n=ctx['count'];k=len(ctx['ids'])
    if len(set(source))!=len(source) or len(weights)!=n*len(source) or len(mapped)!=len(source):raise ValueError('Invalid imported skin rows or mapping.')
    destinations=[value for value in mapped if value is not None]
    if len(set(destinations))!=len(destinations) or any(value not in ctx['ids'] for value in destinations):raise ValueError('Imported influence mapping is stale or not one-to-one.')
    result=state if added else core.edit(state,'add',dict(name=payload.get('name') or 'Imported skin'));layer=result['layers'][-1]
    indices={identity:i for i,identity in enumerate(ctx['ids'])};samples={};used=set()
    large=n*k>storage().PACK_THRESHOLD
    for v in range(n):
        values={}
        for j,value in storage().row_entries(weights,v,len(source)):
            if value:
                if mapped[j] is None:raise ValueError('A weighted source influence is unmapped.')
                col=indices[mapped[j]];values[col]=values.get(col,0.)+value;used.add(mapped[j])
        if large:row=storage().SparseWeights(k,values.items())
        else:
            row=[0.]*k
            for col,value in values.items():row[col]=value
        samples[str(v)]=dict(weights=row,coverage=1.)
    layer['samples']=samples;layer['joints']=[identity for identity in ctx['ids'] if identity in used]
    return core.validate(result)


def verify_import(core,before,state,ctx,payload):
    """Readback of both saved authoring rows and the native final skin."""
    if state is None or not state['layers']:raise RuntimeError('Imported authoring data was not retained.')
    previous=core.remap(before,ctx['ids']) if before is not None else None
    if previous is not None and (state['layers'][:-1]!=previous['layers'] or state['base']!=previous['base']):
        raise RuntimeError('Existing layer data changed during import.')
    if previous is None and len(state['layers'])!=1:raise RuntimeError('Unexpected layer data appeared during import.')
    layer=state['layers'][-1];n=ctx['count'];width=len(ctx['ids']);source=payload['source_ids'];columns={identity:i for i,identity in enumerate(ctx['ids'])}
    if len(layer['samples'])!=n or layer['mask'] or not layer['enabled'] or layer['opacity']!=1.:raise RuntimeError('Imported layer coverage was not retained.')
    for v in range(n):
        desired=[0.]*width
        for j,value in storage().row_entries(payload['weights'],v,len(source)):
            if value:desired[columns[payload['mapping'][j]]]+=value
        sample=layer['samples'].get(str(v))
        if not sample or sample['coverage']!=1. or any(abs(a-b)>TOL for a,b in zip(sample['weights'],desired)):
            raise RuntimeError('Saved imported layer differs at vertex {}.'.format(v))
        if any(abs(a-b)>2e-6 for a,b in zip(ctx['weights'][v*width:(v+1)*width],desired)):
            raise RuntimeError('Native imported skin differs at vertex {}.'.format(v))
    return True
