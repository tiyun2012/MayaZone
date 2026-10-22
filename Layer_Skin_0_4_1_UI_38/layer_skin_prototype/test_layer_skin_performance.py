"""Stroke performance changes, with stale edits, native locks and Undo intact."""
import array
import base64
import gc
import weakref
import hashlib
import json
import math
import types
import unittest
import zlib
from unittest import mock

import layer_skin_core as core
import layer_skin_performance as perf
import layer_skin_paint_commit as commits
import test_layer_skin_command as commands


def legacy_encode(state):
    raw=json.dumps(core.validate(state),separators=(',',':'),allow_nan=False,default=core.storage().json_default).encode()
    return base64.b64encode(zlib.compress(raw,6)).decode()


class EncodingTests(unittest.TestCase):
    def state(self,packed=False):
        weights=core.storage().DenseWeights([.75,.25]*3) if packed else [.75,.25]*3
        return core.edit(core.create(weights,3,['a','b'],'topology'),'add',dict(name='Legacy'))
    def test_new_encoding_reads_old_level_six_and_roundtrips_lists_and_packed_buffers(self):
        for packed in (False,True):
            with self.subTest(packed=packed):
                state=self.state(packed);old=legacy_encode(state);new=core.encode(state)
                self.assertNotEqual(old,new)
                self.assertEqual(core.decode(old),core.decode(new));self.assertEqual(core.composite(core.decode(new)),state['base'])
    def test_outer_and_inner_packed_compression_both_use_level_one(self):
        state=self.state(True)
        with mock.patch.object(core.zlib,'compress',wraps=zlib.compress) as compress:core.encode(state)
        self.assertEqual([call.args[1] for call in compress.call_args_list],[1,1])
    def test_invalid_values_are_still_rejected(self):
        state=self.state();state['layers'][0]['mask']={'1':math.nan}
        with self.assertRaises(ValueError):core.encode(state)

    def test_immutable_packed_base_encoding_is_reused_but_changed_samples_are_saved(self):
        state=self.state(True);base=state['base'];core._PACKED_BASE_ENCODINGS.clear()
        original=core.encode(state);edited=core.edit(state,'paint',dict(layer=state['layers'][0]['id'],joint='b',mode='weights',values={'1':.9}))
        self.assertIs(edited['base'],base)
        with mock.patch.object(core.zlib,'compress',wraps=zlib.compress) as compress:updated=core.encode(edited)
        self.assertEqual([call.args[1] for call in compress.call_args_list],[1]);self.assertNotEqual(updated,original)
        self.assertAlmostEqual(core.composite(core.decode(updated))[3],.9+.1*.25)
    def test_packed_cache_releases_payload_when_base_dies_and_obeys_the_budget(self):
        core._PACKED_BASE_ENCODINGS.clear();state=self.state(True);base=state['base'];reference=weakref.ref(base)
        core.encode(state);self.assertTrue(core._PACKED_BASE_ENCODINGS)
        # Small bases also have an existing strong validation cache. Clear it
        # to isolate the serialization cache's weak ownership in this check.
        core._VALID_BASE.clear();del state,base;gc.collect()
        self.assertIsNone(reference());self.assertEqual(core._PACKED_BASE_ENCODINGS,{})
        with mock.patch.object(core,'PACKED_BASE_CACHE_BYTES',1):core.encode(self.state(True))
        self.assertEqual(core._PACKED_BASE_ENCODINGS,{})
    def test_large_validated_base_uses_weak_identity_and_new_invalid_buffer_is_rejected(self):
        count=550000;values=core.storage().DenseWeights([1.,0.])*count
        state=core.create(values,count,['a','b'],'large');base=state['base'];key=(id(base),count,2)
        self.assertIsInstance(core._VALID_BASE[key],weakref.ReferenceType)
        with mock.patch('builtins.min',side_effect=AssertionError('Rescanned immutable base')):core.validate(state)
        replacement=core.storage().DenseWeights(base);replacement[-1]=-1.;invalid=dict(state,base=replacement)
        with self.assertRaisesRegex(ValueError,'nonnegative'):core.validate(invalid)
        ref=weakref.ref(base);del state,base;gc.collect();self.assertIsNone(ref());self.assertNotIn(key,core._VALID_BASE)


class ComparisonTests(unittest.TestCase):
    def test_optional_vector_path_keeps_exact_absolute_tolerance(self):
        a=array.array('d',[.25]*40000);b=array.array('d',a);b[-1]+=.000001
        with mock.patch.object(perf,'COMPARE_CHUNK',8192):
            self.assertTrue(perf.same(a,b,2e-6));self.assertFalse(perf.same(a,b,1e-7))
        self.assertFalse(perf.same(a,b[:-1],2e-6));self.assertEqual(a[0],.25)
    def test_near_zero_does_not_acquire_numpy_relative_tolerance(self):
        a=[1.]*20000;b=[1.+1e-5]*20000
        self.assertFalse(perf.same(a,b,2e-6))
    def test_nan_and_infinity_differences_do_not_pass_the_vector_guard(self):
        a=array.array('d',[0.]*20000)
        for bad in (math.nan,math.inf,-math.inf):
            b=array.array('d',a);b[-1]=bad
            self.assertFalse(perf.same(a,b,2e-6))
    def test_no_numpy_fallback_has_identical_results(self):
        a=[.5]*20000;b=a[:];b[-1]+=.000001
        with mock.patch.object(perf,'numpy_backend',return_value=None):
            self.assertTrue(perf.same(a,b,2e-6));self.assertFalse(perf.same(a,b,1e-7))
    def test_float32_buffers_promote_before_subtraction(self):
        a=array.array('f',[.25]*20000);b=array.array('d',[.25+1e-8]*20000)
        self.assertTrue(perf.same(a,b,2e-8));self.assertFalse(perf.same(a,b,5e-9))
    def test_vector_comparison_never_iterates_packed_values_in_python(self):
        class Packed(array.array):
            def __new__(cls):return array.array.__new__(cls,'d',[.25]*40000)
            def __iter__(self):raise AssertionError('Python scalar iteration')
        a=Packed();b=Packed();b[-1]+=.000001
        if perf.numpy_backend() is None:self.skipTest('Optional NumPy acceleration is unavailable')
        self.assertTrue(perf.same(a,b,2e-6))


class GuardHashTests(unittest.TestCase):
    def setUp(self):
        self.case=commands.CommandTests();self.case.setUp();self.owner=self.case.ns;self.layer=self.case.attach()
        # The real metadata() already supplies exact raw scene bytes. Add that
        # behavior to this recording graph while retaining real command Undo.
        previous=self.owner['metadata']
        def metadata(ctx):
            result=previous(ctx)
            if result[0] is not None:ctx['raw_metadata']=self.case.graph['raw']
            return result
        self.owner['metadata']=metadata;self.assertTrue(perf.install(self.owner))
    def staged(self):
        ctx=self.owner['context']('mesh');_,state=self.owner['metadata'](ctx)
        return ctx,state,self.owner['state_hash'](ctx,state)
    def paint(self,expected,value=.4,vertex='1'):
        return self.case.command('paint',layer=self.layer,joint='b',mode='weights',values={vertex:value},expected=expected)
    def test_staged_stroke_encodes_only_the_new_state_once(self):
        with mock.patch.object(self.owner['core'],'encode',wraps=self.owner['core'].encode) as encode:
            ctx,state,expected=self.staged();encode.reset_mock()
            self.paint(expected)
        self.assertEqual(encode.call_count,1);self.assertAlmostEqual(self.case.weights[3],.4)
    def test_sequential_stroke_uses_published_digest_and_still_encodes_once(self):
        with mock.patch.object(self.owner['core'],'encode',wraps=self.owner['core'].encode) as encode:
            _,_,expected=self.staged();encode.reset_mock();first=self.paint(expected)
            self.assertEqual(encode.call_count,1)
            next_hash=hashlib.sha256(self.case.graph['raw'].encode()).hexdigest()
            encode.reset_mock();second=self.paint(next_hash,.6,'2')
            self.assertEqual(encode.call_count,1)
        second.undoIt();first.undoIt();self.assertEqual(self.case.weights,[1.,0.]*3)
        first.redoIt();second.redoIt();self.assertAlmostEqual(self.case.weights[5],.6)
    def test_legacy_compression_canonicalizes_once_instead_of_trusting_raw_hash(self):
        state=core.decode(self.case.graph['raw']);self.case.graph['raw']=legacy_encode(state)
        ctx,state,expected=self.staged()
        self.assertNotEqual(expected,hashlib.sha256(self.case.graph['raw'].encode()).hexdigest())
        with mock.patch.object(self.owner['core'],'encode',wraps=self.owner['core'].encode) as encode:
            self.staged();encode.reset_mock();self.paint(expected)
        self.assertEqual(encode.call_count,1)
    def test_influence_remapping_cannot_reuse_the_raw_metadata_digest(self):
        self.case.ids=['b','a'];self.case.weights=[0.,1.]*3
        ctx,state,expected=self.staged();self.assertEqual(state['influences'],['b','a'])
        self.assertNotEqual(expected,hashlib.sha256(self.case.graph['raw'].encode()).hexdigest())
        self.paint(expected);self.assertAlmostEqual(self.case.weights[2],.4)
    def test_changed_metadata_and_external_weights_outside_painted_rows_still_reject(self):
        _,_,expected=self.staged();raw=self.case.graph['raw']
        state=core.edit(core.decode(raw),'properties',dict(layer=self.layer,name='External change'))
        self.case.graph['raw']=core.encode(state)
        with self.assertRaisesRegex(ValueError,'changed during the stroke'):self.paint(expected)
        self.case.graph['raw']=raw;self.case.weights[4:6]=[.5,.5]
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.paint(expected)
        self.assertEqual(self.case.graph['raw'],raw);self.assertEqual(self.case.weights[4:6],[.5,.5])
    def test_unassociated_or_edited_state_cannot_use_a_contexts_cached_digest(self):
        ctx,state,expected=self.staged();edited=core.edit(state,'properties',dict(layer=self.layer,name='Changed in memory'))
        self.assertNotEqual(self.owner['state_hash'](ctx,edited),expected)
    def test_hash_cache_is_bounded_and_retains_no_state_or_buffer(self):
        ctx,state,expected=self.staged();runtime=self.owner['_layer_skin_performance_runtime']
        for i in range(perf.HASH_LIMIT+10):
            edited=core.edit(state,'properties',dict(layer=self.layer,name=str(i)))
            raw=core.encode(edited);self.owner['remember'](raw,edited,self.case.weights)
        self.assertEqual(len(runtime['hashes']),perf.HASH_LIMIT)
        for key,value in runtime['hashes'].items():
            self.assertIsInstance(key[0],str);self.assertIsInstance(key[1],tuple);self.assertIsInstance(value,str)
    def test_codec_refresh_invalidates_hashes_without_reusing_an_object_id(self):
        ctx,state,expected=self.staged();original=self.owner['core'].encode
        with mock.patch.object(self.owner['core'],'encode',side_effect=original) as encode:
            self.assertEqual(self.owner['state_hash'](ctx,state),expected);self.assertEqual(encode.call_count,1)
            self.assertTrue(all(key[2] is encode for key in self.owner['_layer_skin_performance_runtime']['hashes']))
    def test_native_write_failure_rolls_back_metadata_weights_and_cannot_seed_new_digest(self):
        _,_,expected=self.staged();before=self.case.graph['raw'];keys=list(self.owner['_layer_skin_performance_runtime']['hashes'])
        self.case.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.paint(expected)
        self.assertEqual(self.case.graph['raw'],before);self.assertEqual(self.case.weights,[1.,0.]*3)
        self.assertEqual(list(self.owner['_layer_skin_performance_runtime']['hashes']),keys)
    def test_refresh_and_receipt_wrappers_remain_idempotent_and_keep_registered_class(self):
        cls=self.owner['LayerCommand'];commits.install(self.owner);perf.install(self.owner)
        methods=(self.owner['remember'],self.owner['prepare_edit'],cls.doIt)
        for i in range(4):perf.install(self.owner);commits.install(self.owner)
        self.assertEqual(methods,(self.owner['remember'],self.owner['prepare_edit'],cls.doIt));self.assertIs(cls,self.owner['LayerCommand'])
    def test_warm_install_bypasses_the_legacy_encoder_guard_and_preserves_old_undo(self):
        _,_,expected=self.staged();previous=self.paint(expected,.2,'0');cls=self.owner['LayerCommand']
        native=self.owner['prepare_edit']
        def legacy(ctx,meta,state,action,data):
            if data.get('expected') and data['expected']!=hashlib.sha256(self.owner['core'].encode(state).encode()).hexdigest():
                raise ValueError('Legacy guard rejected')
            return native(ctx,meta,state,action,data)
        self.owner['prepare_edit']=legacy;perf.install(self.owner)
        with mock.patch.object(self.owner['core'],'encode',wraps=self.owner['core'].encode) as encode:
            _,_,expected=self.staged();encode.reset_mock();current=self.paint(expected,.7)
            self.assertEqual(encode.call_count,1)
        self.assertIs(self.owner['LayerCommand'],cls);current.undoIt();previous.undoIt()
        self.assertEqual(self.case.weights,[1.,0.]*3);previous.redoIt();current.redoIt();self.assertAlmostEqual(self.case.weights[3],.7)
    def test_packed_base_and_composite_are_budgeted_as_packed_data_and_reused(self):
        count=200000;width=16;base=core.storage().DenseWeights([1.]+[0.]*(width-1))*count
        state=core.edit(core.create(base,count,['j'+str(i) for i in range(width)],'packed'),'add',dict(name='Packed'))
        self.assertLess(perf.state_cost(state),64*1024*1024)
        raw=self.owner['core'].encode(state);self.owner['remember'](raw,state,base)
        key=hashlib.sha256(raw.encode()).hexdigest();self.assertIs(self.owner['_decoded'][key][0],state)
        self.assertIs(self.owner['expected_weights'](state),base)
        # Adding an oversized reference remains over budget and is not pinned.
        state=dict(state,reference={'points':range(200000)})
        self.assertGreater(perf.state_cost(state),64*1024*1024)
    def test_large_sequential_native_metadata_keeps_the_immutable_base_and_composite(self):
        count=200000;width=16;self.case.ids=['j'+str(i) for i in range(width)]
        self.case.weights=core.storage().DenseWeights([1.]+[0.]*(width-1))*count
        backend=self.owner['core'];state=backend.edit(backend.create(self.case.weights,count,self.case.ids,'packed'),'add',dict(name='Packed'))
        self.layer=state['layers'][0]['id'];self.case.graph['raw']=backend.encode(state)
        self.owner['remember'](self.case.graph['raw'],state,self.case.weights)
        fixture=commands.regression.PluginLoaderTests();fixture.setUp();native=fixture.execute()['metadata']
        self.owner['metadata']=types.FunctionType(native.__code__,self.owner)
        self.owner['cmds'].listConnections=lambda plug,**kw:['metadata'] if plug=='skin.message' else ['mesh-node']
        self.owner['cmds'].attributeQuery=lambda *args,**kw:True
        def context(target):return dict(shape='mesh',skin='skin',fn=self.case.skin,dag=self.case.dag,count=count,ids=list(self.case.ids),topology='packed',weights=backend.storage().copy_values(self.case.weights))
        self.owner['context']=context;perf.install(self.owner)
        self.data_joint='j1'
        with mock.patch.object(backend,'_encode_value',wraps=backend._encode_value) as packing:
            first=self.case.command('paint',layer=self.layer,joint='j1',mode='weights',values={'1':.4},expected=hashlib.sha256(self.case.graph['raw'].encode()).hexdigest())
            second=self.case.command('paint',layer=self.layer,joint='j1',mode='weights',values={'2':.6},expected=hashlib.sha256(self.case.graph['raw'].encode()).hexdigest())
        self.assertFalse(any(call.args[0] is state['base'] for call in packing.call_args_list))
        live_state=self.owner['_decoded'][hashlib.sha256(self.case.graph['raw'].encode()).hexdigest()][0]
        self.assertIs(live_state['base'],state['base']);self.assertEqual(self.case.weights[width+1],.4);self.assertEqual(self.case.weights[2*width+1],.6)
        second.undoIt();first.undoIt();self.assertEqual(self.case.weights[width+1],0.)
    def test_full_context_is_still_read_for_every_sequential_stroke(self):
        _,_,expected=self.staged()
        with mock.patch.dict(self.owner,context=mock.Mock(wraps=self.owner['context'])):
            self.paint(expected)
            self.paint(hashlib.sha256(self.case.graph['raw'].encode()).hexdigest(),.5,'2')
            self.assertEqual(self.owner['context'].call_count,2)
    def test_clear_cache_drops_transient_hashes(self):
        self.staged();self.assertTrue(self.owner['_layer_skin_performance_runtime']['hashes']);self.owner['clear_cache']()
        self.assertEqual(self.owner['_layer_skin_performance_runtime']['hashes'],{})


class ScopedPlugTests(unittest.TestCase):
    def setUp(self):
        self.case=commands.NativeGuardTests();self.case.setUp();self.owner=self.case.ns;self.ctx=self.case.ctx
        self.lookups=[];self.leaves=[]
        def plug(name):return types.SimpleNamespace(isLocked=False,isDestination=False,name=lambda:name)
        def row(vertex):
            self.lookups.append(vertex);return self.rows[vertex]
        self.root=plug('skin.weightList');self.root.elementByLogicalIndex=row;self.rows={}
        for vertex in range(3):
            leaves=[plug('skin.weightList[%d].weights[%d]'%(vertex,i)) for i in (0,5)]
            values=plug('skin.weightList[%d].weights'%vertex)
            values.numElements=lambda:2;values.elementByPhysicalIndex=lambda index,leaves=leaves:leaves[index]
            entry=plug('skin.weightList[%d]'%vertex);entry.child=lambda index,values=values:values
            self.rows[vertex]=entry;self.leaves.append(leaves)
        self.ctx['fn'].findPlug=lambda *args:self.root
        self.ctx['fn'].getConnections=mock.Mock(side_effect=AssertionError('Whole skin connection enumeration'))
        self.owner['cmds'].listAttr=mock.Mock(side_effect=AssertionError('Whole weightList enumeration'))
    def check(self):return perf.preflight(self.owner,self.ctx,None,[1,0]*3,[1,0,.5,.5,1,0],[1])
    def test_small_stroke_inspects_only_changed_row_without_global_multi_scan(self):
        self.assertEqual(self.check(),[1]);self.assertEqual(self.lookups,[1])
        self.owner['cmds'].listAttr.assert_not_called();self.ctx['fn'].getConnections.assert_not_called()
    def test_unlocked_parent_does_not_hide_locked_leaf_in_sparse_logical_column(self):
        self.leaves[1][1].isLocked=True
        with self.assertRaisesRegex(ValueError,'locked.*weights\\[5\\]'):self.check()
    def test_row_array_and_leaf_drivers_are_all_rejected(self):
        for target in (self.rows[1],self.rows[1].child(0),self.leaves[1][0]):
            with self.subTest(name=target.name()):
                target.isDestination=True
                with self.assertRaisesRegex(ValueError,'another driver'):self.check()
                target.isDestination=False
    def test_row_and_weight_array_locks_are_rejected(self):
        for target in (self.rows[1],self.rows[1].child(0)):
            target.isLocked=True
            with self.assertRaisesRegex(ValueError,'locked'):self.check()
            target.isLocked=False
    def test_unevaluated_connected_leaf_cannot_escape_a_scoped_guard(self):
        values=self.rows[1].child(0);values.numElements=lambda:0;values.evaluateNumElements=lambda:2
        self.leaves[1][1].isDestination=True
        with self.assertRaisesRegex(ValueError,'another driver'):self.check()
    def test_unaffected_locks_and_drivers_stay_untouched(self):
        self.leaves[0][0].isLocked=True;self.rows[2].isDestination=True
        self.assertEqual(self.check(),[1]);self.assertEqual(self.lookups,[1])
    def test_flood_retains_the_bulk_guard_and_affected_row_filter(self):
        self.owner['cmds'].listAttr=mock.Mock(return_value=['weightList[1].weights[0]'])
        self.ctx['fn'].getConnections=mock.Mock(return_value=[])
        with mock.patch.object(perf,'SCOPED_PLUG_LIMIT',0),self.assertRaisesRegex(ValueError,'locked'):self.check()
        self.owner['cmds'].listAttr.assert_called_once_with('skin.weightList',locked=True,multi=True)


if __name__=='__main__':unittest.main(verbosity=2)
