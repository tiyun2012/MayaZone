"""CPU-only UI31/UI32 guard/persistence comparison. Does not time Maya.

python benchmark_stroke_guards.py --vertices 200000 --influences 16 --repeat 3
Requires NumPy to generate the representative fixture; the tool does not.
Timings exclude native getWeights/setWeights, topology, Maya scheduling and VP2.
"""
import argparse
import base64
import json
import platform
import statistics
import time
import zlib
import numpy as np
import layer_skin_core as core
import layer_skin_performance as perf


def legacy_encode(state):
    base=state['base']
    if hasattr(base,'itemsize') and len(base)*base.itemsize>8*1024*1024:
        # UI31 did not retain validation for large packed bases.
        core._VALID_BASE.pop((id(base),state['vertex_count'],len(state['influences'])),None)
    state=core.validate(state)
    raw=json.dumps(state,separators=(',',':'),allow_nan=False,default=core.storage().json_default).encode()
    return base64.b64encode(zlib.compress(raw,6)).decode()


def measured(function,repeat):
    seconds=[];result=None
    for _ in range(repeat):
        start=time.perf_counter();result=function();seconds.append(time.perf_counter()-start)
    return dict(median_ms=round(statistics.median(seconds)*1000,3),samples_ms=[round(v*1000,3) for v in seconds]),result


def main():
    p=argparse.ArgumentParser();p.add_argument('--vertices',type=int,default=200000);p.add_argument('--influences',type=int,default=16)
    p.add_argument('--repeat',type=int,default=3);args=p.parse_args();count=args.vertices;width=args.influences
    rng=np.random.default_rng(73);active=min(4,width);rows=rng.random((count,active));rows/=rows.sum(axis=1,keepdims=True)
    matrix=np.zeros((count,width),dtype=np.float64);indices=(np.arange(count)[:,None]+np.arange(active)[None,:])%width
    np.put_along_axis(matrix,indices,rows,axis=1)
    weights=core.storage().DenseWeights(matrix.ravel());state=core.edit(core.create(weights,count,['j'+str(i) for i in range(width)],'cpu-fixture'),'add',dict(name='Paint'))
    layer=state['layers'][0]['id'];state=core.edit(state,'paint',dict(layer=layer,joint='j0',mode='weights',values={str(i):.5 for i in range(min(200,count))}))
    near=core.storage().DenseWeights(weights);near[0]+=1e-16
    old_comparison,_=measured(lambda:all(abs(x-y)<=2e-6 for x,y in zip(weights,near)),args.repeat)
    perf.numpy_backend()  # Cold optional import is outside the staged measurement.
    new_comparison,_=measured(lambda:perf.same(weights,near,2e-6),args.repeat)
    old_encoding,old_raw=measured(lambda:legacy_encode(state),args.repeat)
    new_encoding,new_raw=measured(lambda:core.encode(state),args.repeat)
    assert core.composite(core.decode(old_raw))==core.composite(core.decode(new_raw))
    result=dict(scope='CPU guard/persistence phases only; not native stroke-release latency',python=platform.python_version(),numpy=np.__version__,
        vertices=count,influences=width,weights=count*width,painted_vertices=min(200,count),repeat=args.repeat,
        full_tolerance_comparison=dict(ui31=old_comparison,ui32=new_comparison),
        one_state_encode=dict(ui31_level6=old_encoding,ui32_level1_cached_base=new_encoding),
        metadata_bytes=dict(ui31=len(old_raw),ui32=len(new_raw)),
        staged_command_encode_calls=dict(ui31=2,ui32=1),
        packed_state_and_composite_estimate_bytes=perf.state_cost(state),decoded_cache_cap_bytes=64*1024*1024,packed_base_cache_cap_bytes=core.PACKED_BASE_CACHE_BYTES,
        remaining='Full skin reads, external-edit comparison, state validation/JSON/persistence and write verification remain.')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
