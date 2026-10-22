"""CPU callback replay for radius edits; no native Maya calls or viewport/GPU."""
import json
import platform
import time
from unittest import mock

import layer_skin_core as core
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI


def replay(count,width=8,legacy_updates=10,guarded_updates=200):
    api=FakeAPI();store=core.storage()
    api.ids=['joint-'+str(i) for i in range(width)]
    api.weights=store.DenseWeights([1.]+[0.]*(width-1))*count
    api.state=core.edit(core.create(api.weights,count,api.ids,'topology'),'add',dict(name='Radius benchmark'))
    api.layer=api.state['layers'][0]['id']
    original_context=api.context
    def context(target):return dict(original_context(target),count=count)
    api.context=context
    session=sessions.Session(api);session.start('mesh',api.layer,joint=api.ids[-1],mode='weights')
    original=api.cmds.artUserPaintCtx
    def native(name,**kw):
        result=original(name,**kw)
        if kw.get('edit') and 'radius' in kw:
            # Replay radius-related native callbacks with no painted samples.
            assert session.initialize(session.target)=='-id 1'
            assert session.array_attribute(session.target)==session.buffer.attribute()
            session.before_stroke();session.after_stroke();session.finalize(1)
        return result
    api.cmds.artUserPaintCtx=native
    try:
        result={}
        for name,iterations,guarded in (('unguarded_callback_replay',legacy_updates,False),
                                        ('settings_only_callback_replay',guarded_updates,True)):
            with (mock.patch.object(api,'context',wraps=api.context) as contexts,
                  mock.patch.object(api,'metadata',wraps=api.metadata) as metadata,
                  mock.patch.object(api.paint_buffer,'read',wraps=api.paint_buffer.read) as reads,
                  mock.patch.object(api.paint_buffer,'write',wraps=api.paint_buffer.write) as writes,
                  mock.patch.object(core,'encode',wraps=core.encode) as encodes):
                started=time.perf_counter()
                for i in range(iterations):
                    radius=2.+i*.01
                    if guarded:session.update_brush_settings(radius=radius)
                    else:api.cmds.artUserPaintCtx(api.paint_context,edit=True,radius=radius)
                elapsed=time.perf_counter()-started
                counters=dict(skin_context_reads=contexts.call_count,metadata_reads=metadata.call_count,
                              array_reads=reads.call_count,array_writes=writes.call_count,state_encodes=encodes.call_count)
            if guarded:assert not any(counters.values()),counters
            assert session.stroke is None and not api.calls and api._chunk_depth==0
            result[name]=dict(updates=iterations,seconds=round(elapsed,6),
                              milliseconds_per_update=round(elapsed*1000/iterations,6),counters=counters)
        return dict(vertices=count,influences=width,**result)
    finally:session.close()


def run():
    report=dict(python=platform.python_version(),
                scope='CPU recording-API callback replay; excludes Maya native brush rendering, VP2/GPU and real Maya event ordering',
                note='Both paths use the current session code. UI 30 caches stroke startup; the unguarded path is not the historical UI 28 baseline. These are not native Maya timings.',cases=[])
    for count in (100000,250000):
        case=replay(count);report['cases'].append(case);print(json.dumps(case),flush=True)
    return report


if __name__=='__main__':print(json.dumps(run(),indent=2))
