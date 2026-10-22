"""Layer-summary reuse, invalidation and snapshot lifetime; no Maya required."""
import gc
import types
import unittest
import weakref
import layer_skin_core as core

try:
    from layer_skin_workflow_ui import InfluenceSummaries
except ImportError:
    InfluenceSummaries=None


@unittest.skipIf(InfluenceSummaries is None,'PySide is required to import the UI helper')
class InfluenceSummaryTests(unittest.TestCase):
    def setUp(self):
        self.state=core.create([1.,0.]*3,3,['a','b'],'topology')
        self.state=core.edit(self.state,'add',dict(name='Lower'))
        self.state=core.edit(self.state,'add',dict(name='Upper'))
        self.lower,self.upper=[row['id'] for row in self.state['layers']]
        self.ctx=dict(uuid='mesh-id')
        self.cache=InfluenceSummaries()
        self.reads=[]
        def summarize(state,identity):
            self.reads.append(identity)
            return core.weighted_influences(state,identity)
        self.core=types.SimpleNamespace(weighted_influences=summarize)

    def get(self,identity,state=None,ctx=None):
        state=self.state if state is None else state
        result=self.cache.get(self.core,ctx or self.ctx,state,identity)
        self.assertEqual(result,core.weighted_influences(state,identity))
        return result

    def test_repeated_layer_and_base_round_trips_scan_each_source_once(self):
        for _ in range(4):
            self.get(self.lower);self.get(self.upper);self.get('__base__')
        self.assertEqual(self.reads,[self.lower,self.upper,'__base__'])

    def test_mask_opacity_enable_and_membership_keep_weight_summary(self):
        self.get(self.upper)
        state=core.edit(self.state,'properties',dict(layer=self.upper,opacity=.3,enabled=False,name='Renamed'))
        state=core.edit(state,'paint',dict(layer=self.upper,mode='mask',values={'1':.5}))
        state=core.edit(state,'membership',dict(layer=self.upper,joints=['b']))
        self.get(self.upper,state)
        self.assertEqual(self.reads,[self.upper])

    def test_generated_replacement_and_manual_zero_override_refresh_summary(self):
        self.get(self.upper)
        state=core.edit(self.state,'assign',dict(layer=self.upper,joints=['b'],scope=[0],
            generated={'0':dict(weights=[0.,1.],coverage=1.)}))
        self.assertEqual(self.get(self.upper,state),{'b'})
        state=core.edit(state,'paint',dict(layer=self.upper,mode='weights',joint='b',values={'0':0.}))
        self.assertEqual(self.get(self.upper,state),set())
        self.assertEqual(self.reads,[self.upper]*3)

    def test_new_mesh_influence_order_and_base_snapshot_invalidate_correctly(self):
        self.get('__base__');self.get('__base__',ctx=dict(uuid='other-mesh'))
        state=core.remap(self.state,['b','a']);self.get('__base__',state)
        replacement=dict(state,base=[1.,0.]*3)
        self.assertEqual(self.get('__base__',replacement),{'b'})
        self.assertEqual(self.reads,['__base__']*4)

    def test_editing_one_layer_keeps_other_layers_cached(self):
        for identity in (self.lower,self.upper,'__base__'):self.get(identity)
        state=core.edit(self.state,'paint',dict(layer=self.upper,mode='weights',joint='a',values={'0':.8}))
        self.get(self.lower,state);self.get('__base__',state);self.get(self.upper,state)
        self.assertEqual(self.reads,[self.lower,self.upper,'__base__',self.upper])

    def test_inactive_changed_sources_and_deleted_layers_release_old_snapshots(self):
        class Samples(dict):pass
        samples=Samples({'0':dict(weights=[1.,0.],coverage=1.)})
        self.state['layers'][0]['samples']=samples
        reference=weakref.ref(samples);self.get(self.lower);del samples
        self.state=core.edit(self.state,'paint',dict(layer=self.lower,mode='weights',joint='a',values={'1':.5}))
        self.get(self.upper);gc.collect()
        self.assertIsNone(reference())
        self.get(self.lower)
        self.state=core.edit(self.state,'delete',dict(layer=self.lower))
        self.get(self.upper)
        self.assertNotIn(self.lower,self.cache.entries)

    def test_unknown_layer_ids_never_accumulate_cache_entries(self):
        self.get(self.upper)
        for i in range(40):self.get('missing-'+str(i))
        self.assertEqual(set(self.cache.entries),{self.upper})

    def test_full_stack_keeps_at_most_one_summary_per_live_layer_and_base(self):
        for i in range(core.MAX_LAYERS-2):self.state=core.edit(self.state,'add',dict(name=str(i)))
        identities=[row['id'] for row in self.state['layers']]+['__base__']
        for _ in range(2):
            for identity in identities:self.get(identity)
        self.assertEqual(len(self.cache.entries),core.MAX_LAYERS+1)
        self.assertEqual(self.reads,identities)


if __name__=='__main__':unittest.main()
