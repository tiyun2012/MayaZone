"""CPU callback/header replay only; excludes Maya, brush drawing and commits."""
import json
import platform
import time
from unittest import mock

import layer_skin_core as core
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI


def replay(count,width=8,iterations=500):
    api=FakeAPI();api.ids=['joint-'+str(i) for i in range(width)]
    api.weights=core.storage().DenseWeights([1.]+[0.]*(width-1))*count
    api.state=core.edit(core.create(api.weights,count,api.ids,'topology'),'add',dict(name='Paint cache benchmark'))
    api.layer=api.state['layers'][0]['id'];original_context=api.context
    api.context=lambda target:dict(original_context(target),count=count)
    session=sessions.Session(api);session.start('mesh',api.layer,joint=api.ids[-1],mode='weights')
    # FakeAPI's transaction snapshots copy all fixture weights at openChunk.
    # Unpainted headers need only a balanced marker in this replay; measuring
    # that recording snapshot would add an artificial O(vertex_count) cost.
    chunks=0
    def undo_info(**kw):
        nonlocal chunks
        if kw.get('openChunk'):chunks+=1
        if kw.get('closeChunk'):chunks-=1
    api.cmds.undoInfo=undo_info
    try:
        with (mock.patch.object(api,'context',wraps=api.context) as contexts,
              mock.patch.object(api,'metadata',wraps=api.metadata) as metadata,
              mock.patch.object(api.paint_buffer,'read',wraps=api.paint_buffer.read) as reads,
              mock.patch.object(api.paint_buffer,'write',wraps=api.paint_buffer.write) as writes,
              mock.patch.object(core,'encode',wraps=core.encode) as encodes,
              mock.patch.object(api.cmds,'ls',wraps=api.cmds.ls) as lookups,
              mock.patch.object(api.cmds,'listRelatives',wraps=api.cmds.listRelatives) as parents):
            started=time.perf_counter()
            for _ in range(iterations):
                for name in ('mesh','meshShape','mesh.vtx[1]'):
                    assert session.surface(name)=='meshShape'
                    assert session.array_attribute(name)==session.buffer.attribute()
                session.before_stroke()
                # End an unpainted header without running the real array-diff /
                # commit path. This benchmark measures startup, not painting.
                session.stroke=None;session._end_chunk()
            elapsed=time.perf_counter()-started
            counters=dict(skin_context_reads=contexts.call_count,metadata_reads=metadata.call_count,
                          array_reads=reads.call_count,array_writes=writes.call_count,state_encodes=encodes.call_count,
                          surface_name_lookups=lookups.call_count,parent_queries=parents.call_count)
        assert not any(counters.values()),counters
        assert not api.calls and not api.undo_stack and chunks==0
        return dict(vertices=count,influences=width,iterations=iterations,seconds=round(elapsed,6),
                    milliseconds_per_iteration=round(elapsed*1000/iterations,6),counters=counters)
    finally:session.close()


def run():
    return dict(python=platform.python_version(),
        scope='CPU recording-API replay after staging: cached surface/array aliases and an unpainted stroke header; excludes real paint/Relax, array diff, commit validation, geometry, Maya events and VP2/GPU.',
        cases=[replay(count) for count in (100000,250000)])


if __name__=='__main__':print(json.dumps(run(),indent=2))
