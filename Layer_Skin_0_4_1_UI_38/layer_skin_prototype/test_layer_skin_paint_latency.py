"""Local footprint equivalence, bounded row scans and real Qt preview lifecycle."""
import array
import hashlib
import json
import math
import random
import unittest
from unittest import mock

import layer_skin_brush as brush
import layer_skin_core as core
import layer_skin_performance as perf
import layer_skin_paint_commit as commits
import test_layer_skin_brush_view as views
import test_layer_skin_command as commands


class DirtyRowTests(unittest.TestCase):
    def test_chunks_align_rows_and_keep_changes_at_both_sides_of_boundaries(self):
        n=20000;k=7;a=array.array('d',[.25])*(n*k);b=array.array('d',a)
        expected=[0,1169,1170,1171,n-1]
        for v in expected:b[v*k+k-1]+=.1
        sizes=[];block=perf._block
        def bounded(values,start,end,np):sizes.append(end-start);return block(values,start,end,np)
        with mock.patch.object(perf,'COMPARE_CHUNK',8192),mock.patch.object(perf,'_block',side_effect=bounded):
            self.assertEqual(perf.changed_vertices(a,b,n,k),expected)
        if perf.numpy_backend() is not None:self.assertTrue(sizes);self.assertLessEqual(max(sizes),8192)

    def test_candidate_runs_preserve_scope_order_duplicates_and_exclude_other_changes(self):
        n=12000;k=8;a=array.array('d',[.25])*(n*k);b=array.array('d',a)
        for v in (0,100,5000,11999):b[v*k]+=.1
        scope=[11999,11999]+list(range(1,7000))+[0]
        self.assertEqual(perf.changed_vertices(a,b,n,k,scope),[11999,11999,100,5000,0])
        self.assertEqual(perf.changed_vertices(a,b,n,k,[]),[])

    def test_python_fallback_lists_and_generators_match_reference(self):
        n=9000;k=3;a=[.25]*(n*k);b=a[:];b[4*k]=.5;b[8000*k]=.75
        expected=[4,8000]
        for backend in (None,perf.numpy_backend()):
            with mock.patch.object(perf,'numpy_backend',return_value=backend):
                self.assertEqual(perf.changed_vertices(a,b,n,k,(v for v in range(n))),expected)

    def test_absolute_tolerance_float32_promotion_and_nonfinite_rows(self):
        n=20000;a=array.array('f',[.25])*n;b=array.array('d',[.25+1e-8])*n
        self.assertEqual(perf.changed_vertices(a,b,n,1,tolerance=2e-8),[])
        self.assertEqual(perf.changed_vertices(a,b,n,1,tolerance=5e-9),list(range(n)))
        for bad in (math.nan,math.inf,-math.inf):
            b=array.array('d',[.25])*n;b[-1]=bad
            self.assertEqual(perf.changed_vertices(a,b,n,1),[n-1])

    def test_packed_vector_rows_do_not_use_python_scalar_iteration(self):
        if perf.numpy_backend() is None:self.skipTest('Optional NumPy acceleration is unavailable')
        class Packed(array.array):
            def __iter__(self):raise AssertionError('Full Python weight iteration')
            def __getitem__(self,key):raise AssertionError('Per-row Python slicing')
        a=Packed('d',[.5]*40000);b=Packed('d',[.5]*40000);b[-1]=.25
        self.assertEqual(perf.changed_vertices(a,b,10000,4),[9999])


class ConnectedFootprintTests(unittest.TestCase):
    def test_matches_grid_over_random_graphs_clips_radii_and_disconnected_islands(self):
        rng=random.Random(37)
        for _ in range(20):
            points=[tuple(rng.uniform(-2,2) for _ in range(3)) for v in range(100)]
            graph={v:[u for u in range(100) if u!=v and rng.random()<.025] for v in range(100)}
            clip={v:rng.choice((0.,.2,.8,1.)) for v in range(100)}
            grid=brush.SurfaceGrid(points,.7);connected=brush.ConnectedSurface(points.__getitem__)
            seeds=rng.sample(range(100),5)
            for radius in (.25,1.,3.):
                self.assertEqual(connected.footprint((0.,0.,0.),seeds,graph.__getitem__,radius=radius,clip=clip.__getitem__),
                    grid.footprint((0.,0.,0.),seeds,graph.__getitem__,radius=radius,clip=clip.__getitem__))

    def test_large_mesh_reads_only_connected_footprint_and_boundary(self):
        reads=[];n=250000
        def point(v):reads.append(v);return (float(v),0.,0.)
        def neighbors(v):return [u for u in (v-1,v+1) if 0<=u<n]
        surface=brush.ConnectedSurface(point)
        factors=surface.footprint((100.,0.,0.),[100],neighbors,radius=2.5)
        self.assertEqual(set(factors),set(range(98,103)));self.assertEqual(set(reads),set(range(97,104)))

    def test_clip_boundary_cannot_bridge_and_nearby_island_stays_excluded(self):
        points=[(0.,0.,0.),(.1,0.,0.),(.2,0.,0.),(.01,0.,0.)]
        graph={0:[1],1:[0,2],2:[1],3:[]};surface=brush.ConnectedSurface(points.__getitem__)
        self.assertEqual(surface.footprint((0,0,0),[0],graph.__getitem__,radius=1.,clip=lambda v:0. if v==1 else 1.),{0:1.})

    def test_limit_aborts_connected_growth_and_invalid_radius_is_rejected(self):
        surface=brush.ConnectedSurface(lambda v:(0,0,0))
        with self.assertRaisesRegex(ValueError,'Reduce the radius'):
            surface.footprint((0,0,0),[0],lambda v:[v+1],radius=1.,max_vertices=4)
        for value in (0.,-1.,math.nan,math.inf):
            with self.assertRaises(ValueError):surface.footprint((0,0,0),[0],lambda v:[],radius=value)


class RelaxReceiptCommandTests(unittest.TestCase):
    def setUp(self):
        self.case=commands.CommandTests();self.case.setUp();self.owner=self.case.ns;self.layer=self.case.attach()
        self.scope=dict(shape='mesh',skin='skin',uuid='mesh-node',count=3,ids=['a','b'],topology='topology',
            meta='metadata',layer=self.layer,joint='b',mode='weights')
        self.data=dict(target='mesh',layer=self.layer,mode='weights',samples={'1':dict(weights=[.2,.8],coverage=1.)})
        def invoke(action,data):
            payload=json.loads(data);payload.pop('target');self.command=self.case.command(action,**payload)
        self.owner['cmds'].rtkLayerSkin=invoke;commits.install(self.owner)
    def commit(self):return commits.commit(self.owner,self.data,self.scope,'relax_stroke')

    def test_relax_receipt_uses_exact_saved_state_and_preserves_native_undo_redo(self):
        raw=self.case.graph['raw'];receipt=self.commit()
        self.assertEqual(receipt['state'],core.decode(self.case.graph['raw']))
        self.assertEqual(receipt['weights'],self.case.weights);self.assertAlmostEqual(receipt['weights'][3],.8)
        self.command.undoIt();self.assertEqual(self.case.graph['raw'],raw);self.assertEqual(self.case.weights,[1.,0.]*3)
        self.command.redoIt();self.assertAlmostEqual(self.case.weights[3],.8)

    def test_wrong_action_cannot_claim_a_request_with_matching_token(self):
        original=self.owner['cmds'].rtkLayerSkin
        self.data['values']={'0':.4};self.data['joint']='b'
        self.owner['cmds'].rtkLayerSkin=lambda action,data:original('paint',data)
        self.assertIsNone(self.commit());self.assertAlmostEqual(self.case.weights[1],.4)

    def test_external_edit_outside_relax_scope_and_failed_write_keep_guards(self):
        self.case.weights[-2:]=[.5,.5]
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.commit()
        self.case.weights=[1.,0.]*3;raw=self.case.graph['raw'];self.case.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.commit()
        self.assertEqual(self.case.graph['raw'],raw);self.assertEqual(self.owner['_layer_skin_paint_runtime']['requests'],{})

    def test_warm_runtime_replacement_keeps_old_commands_and_adds_relax_receipts(self):
        old=self.case.command('paint',layer=self.layer,joint='b',mode='weights',values={'0':.3})
        cls=self.owner['LayerCommand'];self.owner['_layer_skin_paint_runtime']['revision']=31
        commits.install(self.owner);self.assertIs(self.owner['LayerCommand'],cls)
        self.assertEqual(self.owner['_layer_skin_paint_runtime']['revision'],37);self.assertIsNotNone(self.commit())
        self.command.undoIt();old.undoIt();self.assertEqual(self.case.weights,[1.,0.]*3)


@unittest.skipIf(views.view_module is None,'PySide is required')
class RelaxPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=views.QtWidgets.QApplication.instance() or views.QtWidgets.QApplication([])
    def setUp(self):
        self.fixture=views.BrushViewTests();self.fixture.app=self.app;self.fixture.setUp()
        self.s=self.fixture.session;self.c=self.fixture.controller;self.api=self.fixture.api
        self.s.relax_settings=lambda:dict(strength=.05,iterations=1,preserve_coverage=True)
    def tearDown(self):self.fixture.tearDown()
    def drag(self):
        for x in range(24,104,4):self.c.apply_point((x,20))
    def install_provider(self):
        def commit(action,data,scope):
            self.api.cmds.rtkLayerSkin(action=action,data=json.dumps(data));raw=core.encode(self.api.state)
            return dict(scope=dict(scope),state=self.api.state,weights=self.api.weights[:],
                raw_metadata=raw,state_hash=hashlib.sha256(raw.encode()).hexdigest())
        self.api.commit_edit=commit

    def test_drag_coalesces_uploads_but_keeps_every_stamp_and_flushes_latest_values(self):
        self.install_provider()
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.),mock.patch.object(self.s,'_write_buffer',wraps=self.s._write_buffer) as write:
            self.c.begin(self.fixture.viewport,(20,20));self.drag()
            self.assertGreater(self.c.transaction.stamps,20);self.assertEqual(write.call_count,1)
            self.assertTrue(self.c._preview_timer.isActive());latest=self.s.values[:]
            self.assertNotEqual(self.api.paint_buffer.read(),latest)
            with mock.patch.object(self.s,'prepare',side_effect=AssertionError('Repeated prepare')):
                self.c.finish()
            self.assertEqual(write.call_count,2);self.assertEqual(self.api.paint_buffer.read(),latest)
        self.assertEqual(self.s.last_stroke['status'],'saved');self.assertEqual(len(self.api.undo_stack),1)
        self.assertFalse(self.c._preview_timer.isActive());self.assertIsNotNone(self.s.take_committed_snapshot())

    def test_timer_publishes_final_pending_move_when_cursor_stops(self):
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.):
            self.c.begin(self.fixture.viewport,(20,20));self.c.apply_point((24,20))
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.04):
            self.c._preview_timeout()
        self.assertEqual(self.api.paint_buffer.read(),self.s.values);self.assertFalse(self.c._preview_timer.isActive())
        self.assertEqual(self.c.preview_uploads,2);self.c.cancel()

    def test_cancel_discards_pending_upload_and_restores_baseline_without_command(self):
        before=self.api.snapshot();baseline=self.s.values[:]
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.):
            self.c.begin(self.fixture.viewport,(20,20));self.drag();self.c.cancel()
        self.c._preview_timeout();self.assertEqual(self.api.paint_buffer.read(),baseline)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertFalse(self.c._preview_timer.isActive())

    def test_failed_receipt_falls_back_to_verified_prepare_and_clears_timer(self):
        self.install_provider();provider=self.api.commit_edit
        def wrong(action,data,scope):receipt=provider(action,data,scope);receipt['scope']['uuid']='other';return receipt
        self.api.commit_edit=wrong
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.):
            self.c.begin(self.fixture.viewport,(20,20));self.drag()
            with mock.patch.object(self.s,'prepare',wraps=self.s.prepare) as prepare:self.c.finish()
        self.assertEqual(prepare.call_count,1);self.assertEqual(self.s.last_stroke['status'],'saved')
        self.assertFalse(self.c._preview_timer.isActive())

    def test_preview_failure_cancels_without_leaving_a_pending_native_write(self):
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.):
            self.c.begin(self.fixture.viewport,(20,20));self.drag()
        original=self.s._write_buffer;failed=[False]
        def write():
            if not failed[0]:failed[0]=True;raise RuntimeError('preview upload failed')
            return original()
        with mock.patch.object(views.view_module.time,'monotonic',return_value=100.04),mock.patch.object(self.s,'_write_buffer',side_effect=write):self.c._preview_timeout()
        self.assertFalse(self.c.drawing);self.assertFalse(self.c._preview_timer.isActive());self.assertEqual(self.api.calls,[])
        self.assertIn('preview upload failed',self.s.last_error)

    def test_begin_reuses_canonical_hash_and_verified_composite_then_checks_live_weights(self):
        self.api._layer_skin_command_owner={'expected_weights':mock.Mock(return_value=self.api.weights[:])}
        self.api.state_hash=mock.Mock(return_value='canonical');self.s._state_hash=None
        with mock.patch.object(core,'encode',side_effect=AssertionError('Repeated encode')),mock.patch.object(core,'composite',side_effect=AssertionError('Repeated composite')):
            self.c.begin(self.fixture.viewport,(20,20));self.assertEqual(self.c.expected,'canonical');self.c.cancel()
        self.api.weights[-2:]=[.5,.5]
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.c.begin(self.fixture.viewport,(20,20))

    def test_begin_updates_stale_view_from_fresh_snapshot_before_delta_receipt(self):
        self.install_provider()
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,joint='b',mode='weights',values={'2':.2}))
        self.api.weights=core.composite(self.api.state)
        self.c.begin(self.fixture.viewport,(20,20));self.assertEqual(self.s.values[2],.2);self.c.finish()
        self.assertEqual(self.s.values[2],.2)


if __name__=='__main__':unittest.main(verbosity=2)
