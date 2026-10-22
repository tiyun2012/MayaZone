"""Safe parts of the three-file proposal: sparse edits and bounded local reuse."""
import array
import base64
import copy
import gc
import json
import math
import random
import types
import unittest
import weakref
import zlib
from unittest import mock

import layer_skin_core as core
import layer_skin_performance as perf
import test_layer_skin_command as commands


def state_with_layer(count=4,width=32):
    ids=['j'+str(i) for i in range(width)]
    state=core.edit(core.create([1.]+[0.]*(width-1),1,ids,'topology'),'add',{}) if count==1 else core.edit(
        core.create(([1.]+[0.]*(width-1))*count,count,ids,'topology'),'add',{})
    layer=state['layers'][0]['id']
    return core.edit(state,'membership',dict(layer=layer,joints=ids)),layer


def dense_rows(state):
    result=copy.deepcopy(state)
    for layer in result['layers']:
        for source in ('samples','generated'):
            layer[source]={key:dict(sample,weights=list(sample['weights'])) for key,sample in layer.get(source,{}).items()}
    return result


class SparseManualTests(unittest.TestCase):
    def test_large_logical_skin_paint_shares_one_hot_sparse_rows_and_roundtrips(self):
        state,layer=state_with_layer()
        with mock.patch.object(core.storage(),'PACK_THRESHOLD',0):
            result=core.edit(state,'paint',dict(layer=layer,joint='j2',mode='weights',values={'0':.2,'1':.8,'2':0.}))
        samples=result['layers'][0]['samples'];row=samples['0']['weights']
        self.assertTrue(row._rtk_sparse_weights);self.assertIs(samples['1']['weights'],row)
        self.assertIs(samples['2']['weights'],row);self.assertEqual(samples['2']['coverage'],0.)
        self.assertEqual(core.decode(core.encode(result)),result);self.assertEqual(state['layers'][0]['samples'],{})

    def test_sparse_and_dense_paint_math_agree_through_transparency_and_redistribution(self):
        state,layer=state_with_layer();dense=state;sparse=state
        for joint,values in [('j1',{'0':.2,'1':.7}),('j2',{'0':.4,'1':.9}),('j1',{'0':.9,'1':0.}),('j2',{'0':0.,'1':0.}),('j1',{'0':0.})]:
            data=dict(layer=layer,joint=joint,mode='weights',values=values)
            with mock.patch.object(core.storage(),'PACK_THRESHOLD',10**9):dense=core.edit(dense,'paint',data)
            with mock.patch.object(core.storage(),'PACK_THRESHOLD',0):sparse=core.edit(sparse,'paint',data)
            self.assertEqual(sparse,dense);self.assertEqual(list(core.composite(sparse)),list(core.composite(dense)))

    def test_lock_budgets_equal_and_proportional_match_dense_edits(self):
        for method in ('equal','proportional'):
            state,layer=state_with_layer(count=1)
            generated=core.storage().SparseWeights(32,[(0,.2),(1,.3),(2,.5)])
            state=core.edit(state,'assign',dict(layer=layer,generated={'0':dict(weights=generated,coverage=.8)},scope=[0]))
            state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['j1'],redistribution=method))
            dense=state;sparse=state
            for joint,value in [('j2',.6),('j0',.1),('j2',0.),('j1',.8)]:
                data=dict(layer=layer,joint=joint,mode='weights',values={'0':value})
                with mock.patch.object(core.storage(),'PACK_THRESHOLD',10**9):dense=core.edit(dense,'paint',data)
                with mock.patch.object(core.storage(),'PACK_THRESHOLD',0):sparse=core.edit(sparse,'paint',data)
                self.assertEqual(sparse,dense)
                sample=sparse['layers'][0]['samples'].get('0') or sparse['layers'][0]['generated']['0']
                self.assertAlmostEqual(sample['weights'][1]*sample['coverage'],.24)

    def test_narrow_and_dense_rows_keep_dense_storage(self):
        state,layer=state_with_layer(width=4)
        with mock.patch.object(core.storage(),'PACK_THRESHOLD',0):
            result=core.edit(state,'paint',dict(layer=layer,joint='j1',mode='weights',values={'0':.5}))
        self.assertIsInstance(result['layers'][0]['samples']['0']['weights'],list)
        row=[1./32]*32;self.assertIs(core._compact_manual_row(row,True),row)

    def test_compaction_does_not_drop_invalid_negative_or_nonfinite_entries(self):
        for bad in (-.5,math.nan,math.inf):
            row=[1.,bad]+[0.]*30
            with self.assertRaises(ValueError):core._compact_manual_row(row,True)

    def test_large_paint_command_keeps_one_native_undo_redo_and_saved_sparse_format(self):
        case=commands.CommandTests();case.setUp();case.ids=['j'+str(i) for i in range(32)];case.weights=([1.]+[0.]*31)*3
        case.ns['core']=core;layer=case.attach();before=case.graph['raw']
        with mock.patch.object(core.storage(),'PACK_THRESHOLD',0):
            cmd=case.command('paint',layer=layer,joint='j2',mode='weights',values={'1':.7})
        saved=case.graph['raw'];state=core.decode(saved)
        self.assertTrue(state['layers'][0]['samples']['1']['weights']._rtk_sparse_weights)
        self.assertAlmostEqual(case.weights[32+2],.7)
        cmd.undoIt();self.assertEqual(case.graph['raw'],before);self.assertEqual(case.weights,([1.]+[0.]*31)*3)
        cmd.redoIt();self.assertEqual(case.graph['raw'],saved);self.assertAlmostEqual(case.weights[32+2],.7)


class LocalMemoTests(unittest.TestCase):
    def test_manual_nested_and_dictionary_mutations_are_revalidated_every_encode(self):
        changes=[lambda s:s['layers'][0]['samples']['0'].update(coverage=-.1),
                 lambda s:s['layers'][0]['samples']['0']['weights'].__setitem__(0,-.1),
                 lambda s:s['layers'][0]['samples'].update({'9999':dict(weights=[1.]+[0.]*31,coverage=1.)})]
        for change in changes:
            state,layer=state_with_layer()
            state=core.edit(state,'paint',dict(layer=layer,joint='j0',mode='weights',values={'0':.5}))
            core.encode(state);change(state)
            with self.assertRaises(ValueError):core.encode(state)

    def test_shared_row_validation_is_reused_only_within_one_call_but_all_coverages_checked(self):
        row=core.storage().SparseWeights(32,[(1,1.)]);samples={str(i):dict(weights=row,coverage=.5) for i in range(1000)}
        valid_keys=frozenset(samples);original=core.storage().row_valid
        with mock.patch.object(core.storage(),'row_valid',wraps=original) as check:
            core._validate_samples(samples,valid_keys,32);self.assertEqual(check.call_count,1)
            core._validate_samples(samples,valid_keys,32);self.assertEqual(check.call_count,2)
            samples['999']['coverage']=-1.
            with self.assertRaises(ValueError):core._validate_samples(samples,valid_keys,32)

    def test_local_validation_releases_rows_after_the_call(self):
        row=core.storage().DenseWeights([1.]+[0.]*31);ref=weakref.ref(row)
        samples={'0':dict(weights=row,coverage=1.)};core._validate_samples(samples,{'0'},32)
        del row,samples;gc.collect();self.assertIsNone(ref())

    def test_encoded_sparse_payload_is_canonical_and_reused_only_for_this_encode(self):
        state,layer=state_with_layer();row=core.storage().SparseWeights(32,[(1,1.)])
        state['layers'][0]['samples']={str(i):dict(weights=row,coverage=.5) for i in range(4)}
        raw=json.dumps(core.validate(state),separators=(',',':'),allow_nan=False,default=core._encode_value).encode()
        expected=base64.b64encode(zlib.compress(raw,core.COMPRESSION_LEVEL)).decode()
        original=core._encode_value
        with mock.patch.object(core,'_encode_value',wraps=original) as encode:
            self.assertEqual(core.encode(state),expected);self.assertEqual(encode.call_count,1)
            core.encode(state);self.assertEqual(encode.call_count,2)

    def test_sparse_packed_reuse_has_byte_and_entry_limits_and_preserves_rows(self):
        with mock.patch.object(core,'PACKED_ROW_CACHE_BYTES',2400),mock.patch.object(core,'LOCAL_ROW_CACHE_LIMIT',2):
            cache=core._PackedRows(64)
            for i in range(20):
                row=core.storage().SparseWeights(64,[(i,1.)]);packed=cache.get(row)
                self.assertEqual(packed[i],1.);self.assertLessEqual(len(cache.rows),2)
                self.assertLessEqual(sum(core.sys.getsizeof(entry[1])+128 for entry in cache.rows.values()),2400)
        with mock.patch.object(core,'PACKED_ROW_CACHE_BYTES',0):
            cache=core._PackedRows(64);cache.get(row)
        self.assertEqual(cache.rows,{})

    def test_packed_memo_disables_and_releases_entries_when_rows_are_unique(self):
        cache=core._PackedRows(64)
        for i in range(1000):
            value=.1+i/2000;row=core.storage().SparseWeights(64,[(0,value),(1,1.-value)])
            self.assertEqual(list(cache.get(row)[:2]),[value,1.-value])
        self.assertFalse(cache.enabled);self.assertEqual(cache.rows,{})

    def test_full_and_partial_composition_expand_a_shared_full_alpha_row_once(self):
        state,layer=state_with_layer(count=20);row=core.storage().SparseWeights(32,[(1,1.)])
        state['layers'][0]['samples']={str(i):dict(weights=row,coverage=1.) for i in range(20)}
        original=type(row).packed
        with mock.patch.object(type(row),'packed',autospec=True,side_effect=original) as packed:
            core.composite(state);self.assertEqual(packed.call_count,1)
            core.composite_vertices(state,[0,2,4,6]);self.assertEqual(packed.call_count,2)

    def test_fractional_sparse_composition_does_not_iterate_or_expand_dense_weights(self):
        class Sparse(core.storage().SparseWeights):
            def __iter__(self):raise AssertionError('Dense sparse-row iteration')
            def packed(self):raise AssertionError('Dense sparse-row expansion')
        state,layer=state_with_layer();state['layers'][0]['samples']={'0':dict(weights=Sparse(32,[(2,1.)]),coverage=.5)}
        self.assertEqual(core.composite(state)[2],.5);self.assertEqual(core.composite_vertices(state,[0])[2],.5)

    def test_packed_rows_are_released_after_composition_and_not_changed_by_later_layers(self):
        state,layer=state_with_layer();row=core.storage().SparseWeights(32,[(1,1.)]);refs=[]
        state['layers'][0]['samples']={str(i):dict(weights=row,coverage=1.) for i in range(4)}
        state=core.edit(state,'add',{});second=state['layers'][-1]
        second['samples']={'0':dict(weights=core.storage().SparseWeights(32,[(2,1.)]),coverage=.5)}
        original=type(row).packed
        def packed(value):result=original(value);refs.append(weakref.ref(result));return result
        with mock.patch.object(type(row),'packed',packed):result=core.composite(state)
        self.assertEqual(result[1:3],[.5,.5]);self.assertEqual(result[33],1.)
        self.assertEqual(row.entries,((1,1.),));gc.collect();self.assertTrue(all(ref() is None for ref in refs))

    def test_random_mixed_sparse_layers_match_dense_composition_and_arbitrary_vertex_order(self):
        rng=random.Random(38);state,layer=state_with_layer(count=20)
        for index in range(4):
            if index:state=core.edit(state,'add',{});layer=state['layers'][-1]['id']
            current=state['layers'][-1];current['opacity']=[1.,.4,.8,1.][index];current['enabled']=index!=3
            for v in range(20):
                columns=rng.sample(range(32),3);values=[rng.random() for _ in columns];total=sum(values)
                weights=core.storage().SparseWeights(32,zip(columns,[x/total for x in values]))
                source=current['samples'] if v%3 else current['generated']
                source[str(v)]=dict(weights=weights,coverage=rng.choice((0.,.3,1.)))
                current['mask'][str(v)]=rng.choice((0.,.2,1.))
        expected=core.composite(dense_rows(state));actual=core.composite(state)
        self.assertTrue(perf.same(actual,expected,1e-12));vertices=[7,2,7,0,19]
        self.assertTrue(perf.same(core.composite_vertices(state,vertices),[x for v in vertices for x in expected[v*32:(v+1)*32]],1e-12))


class ScatteredRowsTests(unittest.TestCase):
    def fixture(self,width=32):
        n=4000;a=array.array('d',[.25])*(n*width);b=array.array('d',a)
        for v in range(0,n,3):b[v*width]=.5
        return n,width,a,b
    def expected(self,a,b,k,scope):return [v for v in scope if not perf.same(a[v*k:(v+1)*k],b[v*k:(v+1)*k],1e-12)]

    def test_mixed_contiguous_scattered_duplicate_and_generator_scopes_keep_exact_order(self):
        n,k,a,b=self.fixture();scope=[100,3,5,3]+list(range(1000))+[v*3 for v in range(600)]+list(range(2500,3500))
        self.assertEqual(perf.changed_vertices(a,b,n,k,(v for v in scope)),self.expected(a,b,k,scope))

    def test_scattered_batches_are_bounded_and_avoid_per_row_python_slices(self):
        np=perf.numpy_backend()
        if np is None:self.skipTest('Optional NumPy acceleration is unavailable')
        class Packed(array.array):
            def __getitem__(self,key):raise AssertionError('Per-row Python slicing')
        n=4000;k=32;a=Packed('d',[.25]*(n*k));b=Packed('d',[.25]*(n*k));scope=list(range(0,1800,3))
        for v in scope:b[v*k]=.5
        sizes=[]
        class Backend:
            def __getattr__(self,name):return getattr(np,name)
            def all(self,values,*args,**kwargs):sizes.append(values.size);return np.all(values,*args,**kwargs)
        with mock.patch.object(perf,'numpy_backend',return_value=Backend()),mock.patch.object(perf,'COMPARE_CHUNK',4096):
            self.assertEqual(perf.changed_vertices(a,b,n,k,scope),scope)
        self.assertTrue(sizes);self.assertLessEqual(max(sizes),4096)

    def test_small_selections_do_not_construct_gather_views(self):
        n,k,a,b=self.fixture();scope=[0,7,14,21]
        with mock.patch.object(perf,'numpy_backend',side_effect=AssertionError('Small selection optional import')):
            self.assertEqual(perf.changed_vertices(a,b,n,k,scope),[0,21])

    def test_float32_promotion_and_nonfinite_scattered_rows_keep_absolute_tolerance(self):
        n=30000;a=array.array('f',[.25])*n;b=array.array('d',[.25+1e-8])*n;scope=list(range(0,n,7))
        self.assertEqual(perf.changed_vertices(a,b,n,1,scope,2e-8),[])
        self.assertEqual(perf.changed_vertices(a,b,n,1,scope,5e-9),scope)
        for bad in (math.nan,math.inf,-math.inf):
            b=array.array('d',[.25])*n;b[scope[-1]]=bad
            self.assertEqual(perf.changed_vertices(a,b,n,1,scope),[scope[-1]])

    def test_lists_noncontiguous_buffers_and_missing_numpy_keep_row_fallback(self):
        n,k,a,b=self.fixture();scope=list(range(0,n,5));expected=self.expected(a,b,k,scope)
        self.assertEqual(perf.changed_vertices(list(a),list(b),n,k,scope),expected)
        with mock.patch.object(perf,'numpy_backend',return_value=None):self.assertEqual(perf.changed_vertices(a,b,n,k,scope),expected)
        np=perf.numpy_backend()
        if np is not None:
            left=np.zeros(len(a)*2);right=left.copy();left[::2]=a;right[::2]=b
            self.assertEqual(perf.changed_vertices(left[::2],right[::2],n,k,scope),expected)


if __name__=='__main__':unittest.main(verbosity=2)
