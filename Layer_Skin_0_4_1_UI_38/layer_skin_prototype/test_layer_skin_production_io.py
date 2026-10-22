"""Production-size buffer/file cases and native batching with recorded API calls."""
import array
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import zlib

import layer_skin_core as core
import layer_skin_io as io
import layer_skin_memory as memory
import test_layer_skin_io as fixtures
import test_layer_skin_io_command as command_fixtures


def sparse_snapshot(count=20001,width=128):
    store=core.storage()
    values=store.SparseMatrix(count,width,array.array('Q',range(count+1)),
                             array.array('I',(v%width for v in range(count))),array.array('d',[1.])*count)
    return dict(count=count,topology='0'*64,influences=[dict(uuid='j'+str(i),path='|j'+str(i)) for i in range(width)],
                weights=values,geometry='base',skinning_method=0)


class StorageTests(unittest.TestCase):
    def setUp(self):self.store=core.storage()
    def test_packed_buffer_budget_supports_normal_meshes_above_old_guard(self):
        self.assertEqual(self.store.dimensions(100000,339),33900000)
        self.assertGreater(core.MAX_VALUES,33900000)
        for count,width in ((0,2),(True,2),(1,0),(1,4097),(self.store.MAX_VALUES,2)):
            with self.subTest(count=count,width=width),self.assertRaises(ValueError):self.store.dimensions(count,width)
    def test_small_states_keep_legacy_lists_and_packed_states_roundtrip_losslessly(self):
        state=core.create([1.,0.]*3,3,['a','b'],'topology')
        self.assertIsInstance(state['base'],list)
        with mock.patch.object(self.store,'PACK_THRESHOLD',4):
            state=core.create([1.-1e-15,1e-15]*3,3,['a','b'],'topology')
            self.assertIsInstance(state['base'],array.array)
            encoded=core.encode(state);actual=core.decode(encoded)
            self.assertEqual(actual['base'],state['base'])
            self.assertEqual(core.encode(actual),encoded)
            self.assertEqual(actual['base'].itemsize,8)
    def test_packed_base_validation_does_not_retain_large_buffers_in_cache(self):
        count=1050000
        state=core.create(array.array('d',[1.,0.])*count,count,['a','b'],'topology')
        self.assertFalse(any(value is state['base'] for value in core._VALID_BASE.values()))
    def test_packed_and_sparse_codec_rejects_bad_dimensions_checksum_and_bombs(self):
        value=self.store.json_default(self.store.DenseWeights([1.,0.]))
        for changes in ({'count':True},{'count':self.store.MAX_VALUES+1},{'sha256':'wrong'},
                        {'data':base64.b64encode(zlib.compress(b'0'*1000)).decode()}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.store.json_object(dict(value,**changes))
        with self.assertRaises(ValueError):self.store.json_object(dict(value,data=value['data']+'?'))
        with self.assertRaises(ValueError):self.store.SparseWeights(3,[(1.5,1.)])
        with self.assertRaises(ValueError):self.store.SparseWeights(3,[(True,1.)])
        with self.assertRaises(ValueError):self.store.SparseWeights(3,[(1,.5),(1,.5)])
        with self.assertRaises(ValueError):self.store.SparseWeights(3,[(3,1.)])
    def test_sparse_rows_support_editing_masking_remapping_and_serialization(self):
        with mock.patch.object(self.store,'PACK_THRESHOLD',4):
            state=core.create([1.,0.]*3,3,['a','b'],'topology')
            payload=dict(source_ids=['a','b'],mapping=['a','b'],weights=[0.,1.,.4,.6,1.,0.])
            result=io.import_state(core,state,dict(ids=['a','b'],count=3),payload)
            row=result['layers'][0]['samples']['0']['weights']
            self.assertTrue(row._rtk_sparse_weights);self.assertEqual(row[:],[0.,1.])
            self.assertEqual(row[-1],1.);self.assertIs(copy.deepcopy(row),row)
            self.assertEqual(list(core.composite(result)),payload['weights'])
            layer=result['layers'][0]['id']
            painted=core.edit(result,'paint',dict(layer=layer,mode='weights',joint='a',values={'0':.25}))
            self.assertEqual(list(core.composite(painted))[:2],[.25,.75])
            remapped=core.remap(result,['b','new','a'])
            self.assertEqual(list(core.composite(remapped))[:3],[1.,0.,0.])
            self.assertTrue(remapped['layers'][0]['samples']['0']['weights']._rtk_sparse_weights)
            decoded=core.decode(core.encode(result))
            self.assertEqual(decoded['layers'],result['layers'])
            self.assertEqual(core.weighted_influences(decoded,layer),{'a','b'})
    def test_sparse_validation_rejects_nonfinite_non_normalized_and_duplicate_rows(self):
        snapshot=sparse_snapshot(3,2)
        for invalid in ((1.2,0.,0.),(float('nan'),1.,1.),(-1.,1.,1.)):
            weights=snapshot['weights']
            snapshot['weights']=self.store.SparseMatrix(3,2,weights.offsets,weights.columns,array.array('d',invalid))
            with self.assertRaises(ValueError):io.validate(snapshot)
    def test_sparse_index_slice_and_compact_hash_match_dense_values(self):
        weights=sparse_snapshot(3,2)['weights']
        self.assertEqual(list(weights),[1,0,0,1,1,0])
        self.assertEqual(weights[:2],[1,0]);self.assertEqual(weights[1::2],[0,1,0])
        self.assertEqual(weights[-2],1.)
        with self.assertRaises(TypeError):weights.values[0]=.5
        with self.assertRaises(AttributeError):weights.width=10
        expected=hashlib.sha256(array.array('d',weights).tobytes()).hexdigest()
        self.assertEqual(self.store.digest_values(array.array('d',weights)),expected)


class LargeArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'production.rtkskin'
    def test_over_two_million_roundtrip_id_import_layer_save_and_composite(self):
        source=sparse_snapshot();self.assertGreater(len(source['weights']),2_000_000)
        result=io.write(self.path,source);loaded=io.read(self.path)
        self.assertTrue(loaded['weights']._rtk_sparse_matrix)
        self.assertEqual(result['nonzero'],source['count'])
        self.assertLess(self.path.stat().st_size,1024*1024)
        projected=io.project(loaded,dict(count=source['count'],topology=source['topology']))
        self.assertIs(projected['weights'],loaded['weights'])
        ids=[row['uuid'] for row in source['influences']];width=len(ids);count=source['count']
        base=array.array('d',[1.]+[0.]*(width-1))*count
        state=core.create(base,count,ids,source['topology'])
        imported=io.import_state(core,state,dict(ids=ids,count=count),dict(source_ids=ids,mapping=ids,weights=projected['weights']))
        self.assertTrue(imported['layers'][0]['samples']['0']['weights']._rtk_sparse_weights)
        encoded=core.encode(imported);restored=core.decode(encoded)
        actual=core.composite(restored)
        self.assertIsInstance(actual,array.array)
        for v in (0,1,127,128,count-1):
            self.assertEqual(actual[v*width+v%width],1.)
            self.assertEqual(sum(actual[v*width:(v+1)*width]),1.)
        self.assertTrue(io.verify_import(core,state,restored,dict(ids=ids,count=count,weights=actual),
                                        dict(source_ids=ids,mapping=ids,weights=projected['weights'])))
    def test_new_writer_still_uses_v1_typed_arrays_and_legacy_reader_layout(self):
        io.write(self.path,fixtures.snapshot())
        import zipfile
        with zipfile.ZipFile(self.path) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['version'],1)
            for name,record in manifest['arrays'].items():
                raw=archive.read(name+'.bin')
                self.assertEqual(hashlib.sha256(raw).hexdigest(),record['sha256'])
                values=array.array(record['type']);values.frombytes(raw)
                self.assertEqual(len(values),record['count'])
    def test_streamed_reader_never_reads_whole_binary_members(self):
        io.write(self.path,fixtures.snapshot())
        import zipfile
        original=zipfile.ZipFile.read
        def read(archive,name,*args,**kwargs):
            if str(name).endswith('.bin'):raise AssertionError('Binary members must be streamed')
            return original(archive,name,*args,**kwargs)
        with mock.patch.object(zipfile.ZipFile,'read',read):self.assertEqual(io.read(self.path)['weights'],fixtures.snapshot()['weights'])
    def test_sparse_surface_transfer_keeps_sparse_output_and_correct_interpolation(self):
        with mock.patch.object(core.storage(),'PACK_THRESHOLD',1):
            source=fixtures.snapshot();io.write(self.path,source);loaded=io.read(self.path)
            result=io.project(loaded,dict(count=2,points=[(.25,.25,0.),(1.,0.,0.)]),'surface')
            self.assertTrue(result['weights']._rtk_sparse_matrix)
            self.assertEqual(list(result['weights']),[.75,.25,0.,1.])
            self.assertEqual(result['dq'],[.375,.5])
    def test_stream_cancel_keeps_existing_destination_and_removes_temp_file(self):
        self.path.write_bytes(b'previous')
        def cancel():
            if list(Path(self.temp.name).glob('.rtkskin_*')):raise RuntimeError('cancelled stream')
        with self.assertRaisesRegex(RuntimeError,'cancelled stream'):io.write(self.path,fixtures.snapshot(),overwrite=True,check=cancel)
        self.assertEqual(self.path.read_bytes(),b'previous')
        self.assertEqual(list(Path(self.temp.name).glob('.rtkskin_*')),[])


class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture=command_fixtures.ImportCommandTests();self.fixture.setUp()
        self.case=self.fixture.case;self.ns=self.case.ns
    def test_packed_import_native_undo_redo_and_later_batch_failure_recovery(self):
        with mock.patch.object(core.storage(),'PACK_THRESHOLD',4),mock.patch.object(core.storage(),'CHUNK_VALUES',2):
            before=self.case.weights[:]
            command=self.fixture.imported()
            self.assertEqual(self.case.weights,[0.,1.,.4,.6,1.,0.])
            writes=[entry for entry in self.case.log if isinstance(entry,tuple) and entry[0]=='weights']
            self.assertTrue(all(len(entry[3])<=2 for entry in writes))
            command.undoIt();self.assertEqual(self.case.weights,before)
            command.redoIt();self.assertEqual(self.case.weights,[0.,1.,.4,.6,1.,0.])
            command.undoIt()
            original=self.case.skin.setWeights;calls=[]
            def fail_later(*args):
                original(*args);calls.append(1)
                if len(calls)==2:raise RuntimeError('batch two failed')
            self.case.skin.setWeights=fail_later
            with self.assertRaisesRegex(RuntimeError,'batch two failed'):self.fixture.imported()
            self.assertEqual(self.case.weights,before);self.assertFalse(self.case.graph['exists'])
    def test_chunked_native_read_has_bounded_requests_and_preserves_flattened_order(self):
        store=core.storage();calls=[]
        class Component:
            def __init__(self):self.values=[]
            def create(self,*args):return self.values
            def addElements(self,values):self.values.extend(values)
        om=types.SimpleNamespace(MFnSingleIndexedComponent=Component,MFn=types.SimpleNamespace(kMeshVertComponent=1))
        def read(dag,vertices):
            calls.append(list(vertices));return [v*10+j for v in vertices for j in range(3)],3
        with mock.patch.object(store,'CHUNK_VALUES',6),mock.patch.object(store,'PACK_THRESHOLD',4):
            values=memory.read_weights(types.SimpleNamespace(getWeights=read),'mesh',5,3,om)
        self.assertIsInstance(values,array.array)
        self.assertEqual(calls,[[0,1],[2,3],[4]])
        self.assertEqual(list(values),[v*10+j for v in range(5) for j in range(3)])
    def test_cancelled_native_read_stops_between_batches(self):
        fn=types.SimpleNamespace(getWeights=mock.Mock())
        with self.assertRaisesRegex(RuntimeError,'stop'):
            memory.read_weights(fn,None,3,2,self.ns['om'],lambda:(_ for _ in ()).throw(RuntimeError('stop')))
        fn.getWeights.assert_not_called()
    def test_io_computation_restores_cancellation_callback_after_failure(self):
        import layer_skin_io_backend as backend
        import contextlib
        @contextlib.contextmanager
        def computation():yield lambda:None
        service=object.__new__(backend.Backend);service.owner={}
        with mock.patch.object(backend,'computation',computation):
            with self.assertRaisesRegex(RuntimeError,'cancel'):
                with service.computation() as check:
                    self.assertIs(service.owner['_layer_skin_io_check'],check)
                    raise RuntimeError('cancel')
            self.assertNotIn('_layer_skin_io_check',service.owner)
    def test_memory_install_keeps_command_class_old_undo_and_io_auxiliary_extension(self):
        command=self.fixture.imported(self.fixture.payload(dq=[.2,.4,.8],skinning_method=2))
        cls=self.ns['LayerCommand'];original_context=self.ns['context']
        # Record the actual production-context marker without replacing this
        # fixture's independent fake API with a native mesh implementation.
        self.ns['context']=lambda target:original_context(target)
        self.ns['context']._layer_skin_native_context=True
        self.assertTrue(memory.install(self.ns))
        import layer_skin_io_backend as backend
        runtime=backend.install(self.ns)
        self.assertTrue(memory.install(self.ns));self.assertIs(backend.install(self.ns),runtime)
        self.assertIs(self.ns['LayerCommand'],cls)
        command.undoIt();self.assertEqual(self.fixture.dq,[0.,0.,0.]);self.assertEqual(self.fixture.method,0)
        command.redoIt();self.assertEqual(self.fixture.dq,[.2,.4,.8]);self.assertEqual(self.fixture.method,2)

    def test_warm_api_replaces_old_context_guard_and_reads_an_above_limit_mesh(self):
        from layer_skin_ui_refresh import RefreshedAPI
        count,width=6000,339;reads=[]
        dag=types.SimpleNamespace(isInstanced=lambda:False,node=lambda:'mesh-object',fullPathName=lambda:'|mesh|shape')
        class Selection:
            def add(self,name):pass
            def getDagPath(self,index):return dag
        class Component:
            def __init__(self):self.vertices=[]
            def create(self,kind):return self.vertices
            def addElements(self,values):self.vertices.extend(values)
        plug=types.SimpleNamespace(attribute=lambda:'inputGeometry',asMObject=lambda:'input-object')
        entry=types.SimpleNamespace(numChildren=lambda:1,child=lambda i:plug)
        inputs=types.SimpleNamespace(elementByLogicalIndex=lambda i:entry)
        paths=[types.SimpleNamespace(node=lambda i=i:'joint'+str(i)) for i in range(width)]
        def get_weights(path,vertices):
            reads.append(len(vertices)*width)
            return array.array('d',[1.]+[0.]*(width-1))*len(vertices),width
        fn=types.SimpleNamespace(indexForOutputShape=lambda node:0,findPlug=lambda *args:inputs,
                                 influenceObjects=lambda:paths,getWeights=get_weights)
        om=types.SimpleNamespace(MSelectionList=Selection,MFnSingleIndexedComponent=Component,
            MFn=types.SimpleNamespace(kMeshVertComponent=1),MFnMesh=lambda obj:types.SimpleNamespace(numVertices=count),
            MFnAttribute=lambda attr:types.SimpleNamespace(name=attr),
            MFnDependencyNode=lambda node:types.SimpleNamespace(uuid=lambda:types.SimpleNamespace(asString=lambda:node)))
        cmds=types.SimpleNamespace(ls=lambda value=None,**kw:['skin'] if kw.get('type') else ['|mesh|shape'],
                                  nodeType=lambda value:'mesh',listHistory=lambda *args,**kw:['skin'])
        def old_context(target):raise ValueError('Prototype memory limit: 2 million vertex/influence values.')
        old_context._layer_skin_native_context=True
        owner=dict(context=old_context,cmds=cmds,om=om,oma=types.SimpleNamespace(MFnSkinCluster=lambda obj:fn),
                   obj=lambda name:name,topology=lambda mesh:'topology',core=core)
        source=types.SimpleNamespace(core=core,context=old_context)
        self.assertTrue(memory.install(owner))
        api=RefreshedAPI(source,None,owner);ctx=api.context('mesh')
        self.assertIn('input_mesh',ctx);self.assertIsNot(ctx['input_mesh'],ctx['mesh'])
        self.assertEqual(len(ctx['weights']),count*width)
        self.assertIsInstance(ctx['weights'],array.array)
        self.assertGreater(count*width,2_000_000)
        self.assertTrue(all(size<=core.storage().CHUNK_VALUES for size in reads))


if __name__=='__main__':unittest.main(verbosity=2)
