"""CPU-only assignment benchmark; no Maya imports or scene edits."""
import json
import platform
import time

import layer_skin_assignment as geometry


def run(count=100000,width=339):
    ids=['joint-'+str(i) for i in range(width)]
    frames={identity:dict(position=[i%13*8.,i//13*8.,0.],
                          end=[i%13*8.+4.,i//13*8.,0.],
                          x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.],parent=None)
            for i,identity in enumerate(ids)}
    points=[]
    for vertex in range(count):
        start=frames[ids[vertex%width]]['position']
        points.append([start[0]+(-.5 if vertex%9==0 else 2.),
                       start[1]+(vertex%7-3)*.1,(vertex%11-5)*.05])
    reference=dict(points=points,joints=frames,time=0.)
    report=dict(python=platform.python_version(),vertices=count,influences=width,
                scope='CPU-only generator; excludes Maya native IO, binding, metadata encoding and viewport',methods={})
    for method in ('point','bone','axis'):
        cache=geometry.AssignmentCache();settings=dict(method=method)
        started=time.perf_counter();result,info=cache.generate(reference,ids,list(reversed(ids)),settings)
        elapsed=time.perf_counter()-started;tests=cache.vertex_tests
        assert len(result)==count
        for vertex,sample in result.items():
            expected=int(vertex)%width;row=sample['weights']
            assert sample['coverage']==1.
            if getattr(row,'_rtk_sparse_weights',False):assert row.entries==((expected,1.),)
            else:assert row[expected]==1. and sum(row)==1.
        started=time.perf_counter();again,cached=cache.generate(reference,ids,ids,settings)
        repeated=time.perf_counter()-started
        assert again is result and cached['reused'] and cache.vertex_tests==tests
        report['methods'][method]=dict(seconds=round(elapsed,6),cached_seconds=round(repeated,6),
                                     candidate_tests=tests,full_pair_tests=count*width,
                                     assigned_vertices=info['assigned_vertices'],
                                     sparse_rows=bool(getattr(result['0']['weights'],'_rtk_sparse_weights',False)),
                                     verified=True)
        print(method+': '+str(report['methods'][method]),flush=True)
    return report


if __name__=='__main__':print(json.dumps(run(),indent=2))
