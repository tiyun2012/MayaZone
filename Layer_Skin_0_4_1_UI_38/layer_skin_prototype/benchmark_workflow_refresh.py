"""CPU phase comparison with UI 33 policies; excludes native Maya and drawing.

Run with the same Python/PySide environment as the automated UI checks:
    python benchmark_workflow_refresh.py --output WORKFLOW_REFRESH_BENCHMARK.json

Summary fixtures alternate Base and two layers after each has been viewed once.
The previous single-entry cache misses on each revisit. The reference topology
cache below retains UI 33's full cost recount so both policies use identical
neighbor data and API recordings. No timing asserts or Maya speed claims.
"""
import argparse
import array
import json
import platform
import statistics
import time
import types

import layer_skin_core as core
from layer_skin_relax import AdjacencyCache
from layer_skin_workflow_ui import InfluenceSummaries


class PreviousAdjacencyCache(AdjacencyCache):
    def get(self,ctx,vertices,om,check=None):
        key=(ctx.get('uuid',ctx['shape']),ctx['topology'],ctx['count'])
        rows,cost=self.entries.pop(key,({},0));self.bytes-=cost
        iterator=None;answer={}
        for i,v in enumerate(vertices):
            if check and i & 255==0:check()
            if v not in rows:
                if iterator is None:iterator=om.MItMeshVertex(ctx['dag'])
                iterator.setIndex(v);rows[v]=tuple(iterator.getConnectedVertices())
            answer[v]=rows[v]
        cost=len(rows)*100+sum(len(row)*40 for row in rows.values())
        if cost<=self.max_bytes:
            while self.entries and (self.bytes+cost>self.max_bytes or len(self.entries)>=self.max_items):
                _,(_,old)=self.entries.popitem(last=False);self.bytes-=old
            self.entries[key]=(rows,cost);self.bytes+=cost
        return answer


def median_ms(function,repeats):
    samples=[]
    for _ in range(repeats):
        start=time.perf_counter();function();samples.append((time.perf_counter()-start)*1000.)
    return statistics.median(samples)


def compare(before,after,repeats):
    previous=median_ms(before,repeats);current=median_ms(after,repeats)
    return dict(ui33_median_ms=round(previous,6),ui34_median_ms=round(current,6),
                phase_speedup=round(previous/current,2))


def summary_phase(vertices,width,repeats):
    ids=['joint-'+str(i) for i in range(width)]
    base=array.array('d',[1.]+[0.]*(width-1))*vertices
    state=core.create(base,vertices,ids,'fixture-topology')
    for name in ('Assigned','Painted'):state=core.edit(state,'add',dict(name=name))
    generated=dict(weights=(1.,)+(0.,)*(width-1),coverage=1.)
    state['layers'][0]['generated']={str(v):generated for v in range(vertices)}
    state['layers'][1]['samples']={'0':dict(weights=(0.,1.)+(0.,)*(width-2),coverage=1.)}
    scope=['__base__']+[row['id'] for row in state['layers']]
    ctx=dict(uuid='summary-fixture');cache=InfluenceSummaries()
    expected=[core.weighted_influences(state,identity) for identity in scope]
    assert [cache.get(core,ctx,state,identity) for identity in scope]==expected
    result=compare(lambda:[core.weighted_influences(state,identity) for identity in scope],
        lambda:[cache.get(core,ctx,state,identity) for identity in scope],repeats)
    result.update(vertices=vertices,influences=width,lookups_per_sample=len(scope),
        scope='Revisiting unchanged Base, Assigned and Painted summaries',
        retained_summaries=len(cache.entries),
        weight_scans_per_warm_sample=dict(ui33=len(scope),ui34=0))
    return result


def adjacency_phase(vertices,repeats):
    reads=[]
    class Iterator:
        def __init__(self,dag):pass
        def setIndex(self,v):self.v=v
        def getConnectedVertices(self):
            reads.append(self.v)
            return ((self.v-2)%vertices,(self.v-1)%vertices,(self.v+1)%vertices,(self.v+2)%vertices)
    om=types.SimpleNamespace(MItMeshVertex=Iterator)
    ctx=dict(uuid='adjacency-fixture',shape='mesh',topology='fixture-topology',count=vertices,dag=None)
    before=PreviousAdjacencyCache();after=AdjacencyCache()
    before.get(ctx,range(vertices),om);after.get(ctx,range(vertices),om)
    reads.clear();scope=list(range(64))
    assert before.get(ctx,scope,om)==after.get(ctx,scope,om)
    result=compare(lambda:before.get(ctx,scope,om),lambda:after.get(ctx,scope,om),repeats)
    assert not reads
    assert before.bytes==after.bytes
    result.update(cached_vertices=vertices,requested_vertices=len(scope),
        cached_estimated_bytes=after.bytes,native_neighbor_reads_after_warmup=len(reads),
        scope='64 selected vertices after a whole-mesh topology lookup')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='WORKFLOW_REFRESH_BENCHMARK.json')
    parser.add_argument('--repeats',type=int,default=9)
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    result=dict(python=platform.python_version(),platform=platform.platform(),repeats=args.repeats,
        limitations='CPU phase fixtures only. Excludes Maya skin reads/writes, command validation, DG, Artisan, viewport and full layer-switch latency.',
        layer_summary=summary_phase(200000,16,args.repeats),
        selected_relax_topology=adjacency_phase(100000,args.repeats))
    with open(args.output,'w',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
