"""Repeatable CPU-only skin-file benchmark; Python 3.10+, no Maya or Qt.

Run: python skin_io_benchmark.py
Timings exclude Maya API reads, binding, layer metadata, native Undo and viewport.
"""
import platform
import tempfile
import time
from pathlib import Path

import layer_skin_io as skin_io


def run():
    lines=['Layer Skin UI 9 skin-file CPU benchmark',
           'Python '+platform.python_version()+' / '+platform.system(),
           'Wall times are one local run, not Maya performance measurements.']
    with tempfile.TemporaryDirectory(prefix='rtk_skin_io_benchmark_') as folder:
        for count,width in ((100_000,16),(250_000,8)):
            rows=[]
            for v in range(count):
                row=[0.]*width
                for offset,weight in enumerate((.1,.2,.3,.4)):row[(v+offset)%width]=weight
                rows.extend(row)
            snapshot=dict(count=count,topology=skin_io.topology(count,[],[]),weights=rows,
                          influences=[dict(uuid='joint-'+str(j),path='|rig|joint'+str(j),
                                           position=[float(j),0.,0.]) for j in range(width)],
                          skinning_method=2,dq=[(v%101)/100. for v in range(count)],geometry='base')
            path=Path(folder)/('skin_'+str(count)+'.rtkskin')
            started=time.perf_counter();receipt=skin_io.write(path,snapshot);written=time.perf_counter()
            restored=skin_io.read(path);finished=time.perf_counter()
            assert restored['weights']==rows and restored['dq']==snapshot['dq']
            lines.append('{} vertices x {} influences ({} dense values, {} nonzero): '
                         'write {:.6f}s, read {:.6f}s, {} bytes; exact weight/DQ round trip.'.format(
                             count,width,count*width,receipt['nonzero'],written-started,
                             finished-written,receipt['bytes']))
    side=21;points=[(float(x),float(y),0.) for y in range(side) for x in range(side)]
    triangles=[]
    for y in range(side-1):
        for x in range(side-1):
            v=y*side+x;triangles.extend(((v,v+1,v+side),(v+1,v+side+1,v+side)))
    weights=[]
    for x,y,z in points:weights.extend((x/20.,1.-x/20.))
    snapshot=dict(count=len(points),topology=skin_io.topology(len(points),[],[]),points=points,
                  triangles=triangles,weights=weights,influences=[dict(uuid='a',path='|a'),dict(uuid='b',path='|b')],
                  dq=[y/20. for x,y,z in points],skinning_method=2)
    targets=[(x*20./99.,y*20./99.,.125) for y in range(100) for x in range(100)]
    started=time.perf_counter()
    projected=skin_io.project(snapshot,dict(count=len(targets),points=targets),'surface',.2)
    elapsed=time.perf_counter()-started
    error=max(abs(projected['weights'][i*2]-p[0]/20.) for i,p in enumerate(targets))
    dq_error=max(abs(projected['dq'][i]-p[1]/20.) for i,p in enumerate(targets))
    assert error<1e-12 and dq_error<1e-12
    lines.append('Closest surface: {} source vertices / {} triangles -> {} target vertices / 2 influences: '
                 '{:.6f}s including BVH build; weight error {:.3g}, DQ error {:.3g}.'.format(
                     len(points),len(triangles),len(targets),elapsed,error,dq_error))
    lines.append('Archives use four nonzero weights per row. The packed-buffer budget is 1024 MiB; run_production() checks larger logical matrices.')
    return '\n'.join(lines)+'\n'


def run_production(count=100000,width=339):
    """CPU/storage workflow above the old limit; no native Maya or GPU claims."""
    import array
    import gc
    import layer_skin_core as core
    store=core.storage();store.dimensions(count,width)
    if width<4:raise ValueError('Choose at least four influences for this benchmark.')
    offsets=array.array('Q',range(0,count*4+1,4));columns=array.array('I');values=array.array('d')
    patterns=[sorted(((v+i)%width,w) for i,w in enumerate((.1,.2,.3,.4))) for v in range(width)]
    for vertex in range(count):
        for col,value in patterns[vertex%width]:columns.append(col);values.append(value)
    source=store.SparseMatrix(count,width,offsets,columns,values)
    ids=['joint'+str(i) for i in range(width)]
    snapshot=dict(count=count,topology='0'*64,weights=source,
                  influences=[dict(uuid=j,path='|rig|'+j) for j in ids],geometry='base',skinning_method=0)
    stages={}
    def stage(name,operation):
        started=time.perf_counter();value=operation();stages[name]=time.perf_counter()-started;return value
    with tempfile.TemporaryDirectory(prefix='rtk_skin_production_') as directory:
        path=Path(directory)/'production.rtkskin'
        receipt=stage('export_seconds',lambda:skin_io.write(path,snapshot))
        loaded=stage('read_seconds',lambda:skin_io.read(path))
        projected=stage('id_project_seconds',lambda:skin_io.project(loaded,dict(count=count,topology=snapshot['topology'])))
        base=array.array('d',[1.]+[0.]*(width-1))*count
        state=stage('create_base_seconds',lambda:core.create(base,count,ids,snapshot['topology']))
        del base;gc.collect()
        payload=dict(source_ids=ids,mapping=ids,weights=projected['weights'])
        imported=stage('import_layer_seconds',lambda:skin_io.import_state(core,state,dict(count=count,ids=ids),payload))
        encoded=stage('encode_layer_seconds',lambda:core.encode(imported))
        restored=stage('decode_layer_seconds',lambda:core.decode(encoded))
        final=stage('compose_seconds',lambda:core.composite(restored))
        stage('verify_seconds',lambda:skin_io.verify_import(core,state,restored,dict(count=count,ids=ids,weights=final),payload))
        assert loaded['weights']._rtk_sparse_matrix
        assert projected['weights'] is loaded['weights']
        assert isinstance(final,array.array)
        report=dict(vertices=count,influences=width,logical_values=count*width,nonzero=count*4,
                    archive_bytes=receipt['bytes'],encoded_layer_bytes=len(encoded),packed_buffer_bytes=len(final)*final.itemsize,
                    stages=stages,verified=True,excludes='Maya native reads/writes, binding, Undo/Redo and viewport/GPU')
        try:
            import resource
            report['process_peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024. if platform.system()!='Darwin' else 1024.**2)
        except ImportError:pass
        return report


if __name__=='__main__':
    import sys,json
    print(json.dumps(run_production(),indent=2) if '--production' in sys.argv else run(),end='\n')
