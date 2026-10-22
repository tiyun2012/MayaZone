"""CPU phase comparison against UI 36 policies; no Maya/GPU timing claims.

Run: python benchmark_paint_latency.py --output PAINT_LATENCY_BENCHMARK.json
PySide is needed for the preview publication fixture, NumPy is optional.
"""
import argparse
import array
import json
import platform
import statistics
import time
from unittest import mock

import layer_skin_brush as brush
import layer_skin_performance as perf


def median_ms(function,repeats):
    values=[]
    for _ in range(repeats):
        start=time.perf_counter();function();values.append((time.perf_counter()-start)*1000.)
    return statistics.median(values)


def compare(before,after,repeats):
    old=median_ms(before,repeats);new=median_ms(after,repeats)
    return dict(ui36_median_ms=round(old,4),ui37_median_ms=round(new,4),phase_speedup=round(old/new,2))


def row_phase(n,k,repeats):
    a=array.array('d',[1.]+[0.]*(k-1))*n;b=array.array('d',a)
    expected=list(range(100,min(n,164)))+[n-1]
    for v in expected:b[v*k]=.5;b[v*k+1]=.5
    # Exact UI 36 row detector; all guard checks outside this phase are retained.
    scope=list(range(n))
    def previous():return [v for v in scope if not perf.same(a[v*k:(v+1)*k],b[v*k:(v+1)*k],1e-12)]
    def current():return perf.changed_vertices(a,b,n,k,scope)
    assert previous()==current()==expected
    result=compare(previous,current,repeats)
    result.update(vertices=n,influences=k,changed_vertices=len(expected),candidate_vertices=len(scope),
        max_vector_block_values=perf.COMPARE_CHUNK,scope='Dirty-row comparison only; excludes locks and native plugs')
    return result


def geometry_phase(side,repeats):
    n=side*side;points=[(float(v%side),float(v//side),0.) for v in range(n)]
    middle=(side//2)*side+side//2;center=points[middle];radius=3.2
    seeds=[middle,middle+1,middle+side,middle+side+1]
    def neighbors(v):
        x=v%side;y=v//side
        return [u for valid,u in ((x>0,v-1),(x+1<side,v+1),(y>0,v-side),(y+1<side,v+side)) if valid]
    def previous():return brush.SurfaceGrid(points,radius).footprint(center,seeds,neighbors)
    reads=[]
    def current():
        cached={};reads.clear()
        def point(v):
            if v not in cached:cached[v]=points[v];reads.append(v)
            return cached[v]
        return brush.ConnectedSurface(point).footprint(center,seeds,neighbors,radius=radius)
    assert previous()==current()
    result=compare(previous,current,repeats);footprint=current()
    result.update(vertices=n,footprint_vertices=len(footprint),ui36_position_vertices=n,ui37_position_vertices=len(reads),
        scope='Per-gesture grid construction and first footprint; excludes Maya position/ray API and skin read')
    return result


def publication_phase(vertices=250000,events=240):
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    from layer_skin_brush_view import BrushController
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Session:
        closed=False
        def __init__(self):self.values=[0.]*vertices;self.writes=0;self.feedback=0;self.saved=None
        def _write_buffer(self):self.saved=array.array('d',self.values);self.writes+=1
        def reload_feedback(self):self.feedback+=1
    session=Session();controller=BrushController(session);now=[100.]
    with mock.patch('layer_skin_brush_view.time.monotonic',side_effect=lambda:now[0]):
        for event in range(events):
            now[0]=100.+event/events;session.values[event]=event/events
            controller._preview_dirty=True;controller._publish_preview()
        controller._publish_preview(force=True)
    assert list(session.saved)==session.values
    result=dict(vertices=vertices,input_events_per_second=events,ui36_uploads=events,ui37_uploads=session.writes,
        ui36_payload_bytes=events*vertices*8,ui37_payload_bytes=session.writes*vertices*8,
        final_values_match=True,scope='Actual Qt publication gate with a CPU buffer adapter; excludes Maya DG/render time')
    controller.close();app.processEvents()
    return result


def run(repeats):
    np=perf.numpy_backend()
    return dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__ if np is not None else None,
        repeats=repeats,limitation='CPU phases and operation counts only. Full Maya painting/release remains unmeasured.',
        dirty_rows=[row_phase(100000,64,repeats),row_phase(200000,16,repeats),row_phase(250000,64,repeats)],
        connected_geometry=geometry_phase(500,repeats),preview_publication=publication_phase())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='PAINT_LATENCY_BENCHMARK.json')
    parser.add_argument('--repeats',type=int,default=5);args=parser.parse_args()
    report=run(args.repeats)
    with open(args.output,'w',encoding='utf-8') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(report,indent=2))
