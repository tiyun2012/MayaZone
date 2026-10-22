"""UI 37/38 CPU policy comparison; excludes Maya skin reads, DG and viewport.

Run: python benchmark_sparse_edits.py --output SPARSE_EDITS_BENCHMARK.json
The retained reference functions reproduce UI 37's reviewed algorithms.
"""
import argparse
import array
import base64
import json
import platform
import statistics
import time
import zlib
from unittest import mock

import layer_skin_core as core
import layer_skin_performance as perf


def reference_validate_samples(samples,valid_keys,k):
    if not samples:return
    if not valid_keys.issuperset(samples):raise ValueError('Invalid layer vertex.')
    for sample in samples.values():
        if not core.storage().row_valid(sample['weights'],k):raise ValueError('Invalid layer weights.')
        core.unit(sample['coverage'])


def reference_encode(state):
    with mock.patch.object(core,'_validate_samples',reference_validate_samples):state=core.validate(state)
    default=lambda value:core._encode_base(value) if value is state['base'] else core._encode_value(value)
    raw=json.dumps(state,separators=(',',':'),allow_nan=False,default=default).encode()
    return base64.b64encode(zlib.compress(raw,core.COMPRESSION_LEVEL)).decode()


def reference_composite(state):
    result=core.storage().copy_values(state['base']);k=len(state['influences'])
    for layer in state['layers']:
        if not layer['enabled'] or not layer['opacity']:continue
        for key,sample in core.effective_samples(layer).items():
            alpha=layer['opacity']*layer['mask'].get(key,1.)*sample['coverage']
            if not alpha:continue
            start=int(key)*k;weights=sample['weights']
            if alpha==1.:result[start:start+k]=weights.packed() if getattr(weights,'_rtk_sparse_weights',False) else weights
            else:
                inv=1.-alpha
                result[start:start+k]=[inv*a+alpha*b for a,b in zip(result[start:start+k],weights)]
    return result


def reference_changed(before,after,count,width,candidates):
    result=[];np=perf.numpy_backend() if len(before)>=perf.VECTOR_THRESHOLD else None
    def run(first,end):
        if np is None or (end-first)*width<perf.VECTOR_THRESHOLD or width>perf.COMPARE_CHUNK:
            result.extend(v for v in range(first,end) if not perf.same(before[v*width:(v+1)*width],after[v*width:(v+1)*width],1e-12));return
        rows=max(1,perf.COMPARE_CHUNK//width)
        with np.errstate(invalid='ignore',over='ignore'):
            for start in range(first,end,rows):
                stop=min(end,start+rows)
                left=perf._block(before,start*width,stop*width,np).astype(np.float64,copy=False)
                right=perf._block(after,start*width,stop*width,np).astype(np.float64,copy=False)
                equal=np.all((np.abs(left-right)<=1e-12).reshape(stop-start,width),axis=1)
                result.extend((np.flatnonzero(~equal)+start).tolist())
    first=previous=None
    for v in candidates:
        if previous is not None and v!=previous+1:run(first,previous+1);first=None
        if first is None:first=v
        previous=v
    if first is not None:run(first,previous+1)
    return result


def median_ms(function,repeats):
    values=[]
    for _ in range(repeats):
        start=time.perf_counter();function();values.append((time.perf_counter()-start)*1000)
    return statistics.median(values)


def compare(before,after,repeats):
    old=median_ms(before,repeats);new=median_ms(after,repeats)
    return dict(ui37_median_ms=round(old,4),ui38_median_ms=round(new,4),phase_speedup=round(old/new,2))


def composition_phase(n,k,opacity,repeats,unique=False):
    base=core.storage().DenseWeights([1.]+[0.]*(k-1))*n
    state=core.edit(core.create(base,n,['j'+str(i) for i in range(k)],'benchmark'),'add',{})
    layer=state['layers'][0];layer['opacity']=opacity
    rows=[core.storage().SparseWeights(k,[(1+i,.5),(33+i,.5)]) for i in range(16)]
    if unique:
        layer['generated']={str(v):dict(weights=core.storage().SparseWeights(k,[(1,.25+v/n*.5),(33,.75-v/n*.5)]),coverage=1.) for v in range(n)}
    else:layer['generated']={str(v):dict(weights=rows[v%16],coverage=1.) for v in range(n)}
    assert perf.same(reference_composite(state),core.composite(state),1e-12)
    result=compare(lambda:reference_composite(state),lambda:core.composite(state),repeats)
    result.update(vertices=n,influences=k,opacity=opacity,unique_sparse_rows=n if unique else len(rows),scope='Full CPU composite of existing sparse assignment rows')
    return result


def manual_phase(n,k,repeats):
    base=core.storage().DenseWeights([1.]+[0.]*(k-1))*n
    state=core.edit(core.create(base,n,['j'+str(i) for i in range(k)],'benchmark'),'add',{})
    layer=state['layers'][0]['id'];data=dict(layer=layer,joint='j1',mode='weights',values={str(v):.5 for v in range(n)})
    with mock.patch.object(core.storage(),'PACK_THRESHOLD',core.MAX_VALUES):dense=core.edit(state,'paint',data)
    sparse=core.edit(state,'paint',data)
    assert dense==sparse
    old=reference_encode(dense);new=core.encode(sparse)
    assert core.decode(old)==core.decode(new)
    result=compare(lambda:reference_encode(dense),lambda:core.encode(sparse),repeats)
    result.update(vertices=n,influences=k,ui37_encoded_characters=len(old),ui38_encoded_characters=len(new),
        ui37_raw_json_bytes=len(zlib.decompress(base64.b64decode(old))),ui38_raw_json_bytes=len(zlib.decompress(base64.b64decode(new))),
        ui37_unique_weight_rows=len({id(s['weights']) for s in dense['layers'][0]['samples'].values()}),
        ui38_unique_weight_rows=len({id(s['weights']) for s in sparse['layers'][0]['samples'].values()}),
        scope='State validation + encode: UI 37 dense manual-row policy versus UI 38 compact shared rows; packed base warmed')
    return result


def scattered_phase(n,k,size,repeats):
    before=array.array('d',[1.]+[0.]*(k-1))*n;after=array.array('d',before)
    scope=[v*7 for v in range(size)]
    for v in scope[::3]:after[v*k]=.5;after[v*k+1]=.5
    assert reference_changed(before,after,n,k,scope)==perf.changed_vertices(before,after,n,k,scope)
    result=compare(lambda:reference_changed(before,after,n,k,scope),lambda:perf.changed_vertices(before,after,n,k,scope),repeats)
    result.update(vertices=n,influences=k,candidate_vertices=size,scope='Scattered packed-row detection only; native guards unchanged')
    return result


def run(repeats):
    np=perf.numpy_backend()
    return dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__ if np is not None else None,
        repeats=repeats,limitation='CPU phases only; excludes native Maya reads/writes, reference serialization in other workflows and viewport timing.',
        composition=[composition_phase(100000,64,1.,repeats),composition_phase(100000,64,.5,repeats),composition_phase(100000,64,1.,repeats,unique=True)],
        manual_serialization=manual_phase(40000,64,repeats),
        scattered=[scattered_phase(100000,64,size,repeats) for size in (4,64,1024,8192)])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='SPARSE_EDITS_BENCHMARK.json')
    parser.add_argument('--repeats',type=int,default=5);args=parser.parse_args();report=run(args.repeats)
    with open(args.output,'w',encoding='utf-8') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(report,indent=2))
