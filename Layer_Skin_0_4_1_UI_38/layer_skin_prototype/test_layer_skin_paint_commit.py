"""Real command planning/Undo with exact receipts, plus Session/UI delta use."""
import copy
import hashlib
import json
import types
import unittest
from unittest import mock

import layer_skin_core as core
import layer_skin_paint_commit as commits
import test_layer_skin_command as command_tests
from test_layer_skin_ui import Adapter,ui


class CommandReceiptTests(unittest.TestCase):
    def setUp(self):
        self.case=command_tests.CommandTests();self.case.setUp();self.owner=self.case.ns;self.layer=self.case.attach()
        self.scope=dict(shape='mesh',skin='skin',uuid='mesh-node',count=3,ids=['a','b'],topology='topology',
            meta='metadata',layer=self.layer,joint='b',mode='weights')
        self.data=dict(target='mesh',layer=self.layer,joint='b',mode='weights',values={'1':.8})
        def invoke(action,data):
            payload=json.loads(data);payload.pop('target');self.command=self.case.command(action,**payload);return self.command.result
        self.owner['cmds'].rtkLayerSkin=invoke
        self.assertTrue(commits.install(self.owner))
    def commit(self):return commits.commit(self.owner,self.data,self.scope)

    def test_receipt_is_the_exact_saved_state_and_verified_full_weight_buffer(self):
        receipt=self.commit();raw=self.case.graph['raw']
        self.assertEqual(receipt['scope'],self.scope);self.assertEqual(receipt['raw_metadata'],raw)
        self.assertEqual(receipt['state'],core.decode(raw));self.assertEqual(receipt['weights'],self.case.weights)
        self.assertEqual(receipt['state_hash'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(self.owner['_layer_skin_paint_runtime']['requests'],{})

    def test_unrelated_last_cache_entry_is_not_used_for_receipt(self):
        poison=core.edit(core.decode(self.case.graph['raw']),'properties',dict(layer=self.layer,name='Other mesh'))
        original=self.owner['remember']._layer_skin_receipt_original
        def remember(raw,state,weights=None):
            original(raw,state,weights);original(core.encode(poison),poison,[0.,1.]*3)
        self.owner['remember']._layer_skin_receipt_original=remember
        self.owner.pop('_layer_skin_paint_runtime');commits.install(self.owner)
        receipt=self.commit()
        self.assertEqual(receipt['state']['layers'][0]['name'],'Arm')
        self.assertEqual(receipt['raw_metadata'],self.case.graph['raw'])

    def test_mismatched_mesh_identity_produces_no_fast_receipt(self):
        self.scope['uuid']='another-mesh'
        self.assertIsNone(self.commit());self.assertAlmostEqual(self.case.weights[3],.8)
        self.assertTrue(self.command.isUndoable())

    def test_receipt_survives_the_decoded_cache_memory_budget(self):
        self.owner['state_cost']=lambda state:128*1024*1024
        receipt=self.commit()
        self.assertEqual(self.owner['_decoded'],{});self.assertEqual(self.owner['_composed'],{})
        self.assertEqual(receipt['raw_metadata'],self.case.graph['raw']);self.assertAlmostEqual(receipt['weights'][3],.8)

    def test_metadata_changed_after_remember_invalidates_receipt(self):
        original=self.owner['cmds'].rtkLayerSkin
        def invoke(action,data):
            payload=json.loads(data)
            cmd=self.owner['LayerCommand']();cmd.syntax=lambda:None
            cmd.setResult=lambda message:self.case.graph.update(raw='changed-after-commit')
            args=types.SimpleNamespace(isFlagSet=lambda flag:True,flagArgumentString=lambda flag,index:action if flag=='-action' else json.dumps(payload))
            cmd.doIt(args)
        self.owner['cmds'].rtkLayerSkin=invoke
        self.assertIsNone(self.commit());self.assertEqual(self.case.graph['raw'],'changed-after-commit')

    def test_native_write_failure_rolls_back_and_does_not_publish(self):
        before=self.case.graph['raw'];weights=self.case.weights[:];self.case.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.commit()
        self.assertEqual(self.case.graph['raw'],before);self.assertEqual(self.case.weights,weights)
        self.assertEqual(self.owner['_layer_skin_paint_runtime']['requests'],{})
        self.assertEqual(self.owner['_layer_skin_paint_runtime']['stack'],[])

    def test_install_is_idempotent_and_old_undo_objects_keep_working(self):
        previous=self.case.command('paint',layer=self.layer,mode='weights',joint='b',values={'0':.3})
        cls=self.owner['LayerCommand'];method=cls.doIt;commits.install(self.owner)
        self.assertIs(cls.doIt,method);self.commit();current=self.command
        current.undoIt();self.assertAlmostEqual(self.case.weights[1],.3)
        previous.undoIt();self.assertEqual(self.case.weights,[1.,0.]*3)
        previous.redoIt();current.redoIt();self.assertAlmostEqual(self.case.weights[3],.8)

    def test_stale_state_and_external_native_edit_guards_are_unchanged(self):
        self.data['expected']='stale'
        with self.assertRaisesRegex(ValueError,'changed during the stroke'):self.commit()
        self.data.pop('expected');self.case.weights=[.5,.5]*3
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.commit()
        self.assertEqual(self.owner['_layer_skin_paint_runtime']['requests'],{})

    def test_unrequested_commands_do_not_repeat_argument_parsing(self):
        with mock.patch.object(self.owner['om'],'MArgDatabase',wraps=self.owner['om'].MArgDatabase) as parse:
            self.case.command('paint',layer=self.layer,joint='b',mode='weights',values={'0':.4})
        self.assertEqual(parse.call_count,1);self.assertAlmostEqual(self.case.weights[1],.4)


@unittest.skipIf(ui is None,'PySide is required')
class ReceiptViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=ui.QtWidgets.QApplication.instance() or ui.QtWidgets.QApplication([])
    def setUp(self):
        self.api=Adapter();self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh()
        self.window.choose_joint('|b');self.window.paint();self.session=self.window.session;self.last_receipt=None
        def commit(data,scope):
            self.api.cmds.rtkLayerSkin(action='paint',data=json.dumps(data))
            state=core.remap(self.api.state,self.api.ids);raw=core.encode(state)
            self.last_receipt=dict(scope=copy.deepcopy(scope),state=state,weights=list(self.api.weights),
                raw_metadata=raw,state_hash=hashlib.sha256(raw.encode()).hexdigest())
            return self.last_receipt
        self.api.commit_paint=commit
    def tearDown(self):self.window.close();self.app.processEvents()

    def test_successful_native_delta_and_queued_ui_refresh_do_not_reread_or_reupload(self):
        before=self.api.snapshot();values=self.session.values
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,.4])
        with (mock.patch.object(self.session,'prepare',side_effect=AssertionError('Second prepare')),
              mock.patch.object(self.session,'snapshot',side_effect=AssertionError('Second snapshot')),
              mock.patch.object(self.session,'_write_buffer',side_effect=AssertionError('Full buffer reupload')),
              mock.patch.object(self.api,'context',side_effect=AssertionError('Second context')),
              mock.patch.object(self.api,'metadata',side_effect=AssertionError('Second metadata'))):
            self.session.after_stroke();self.window.follow_selection()
        self.assertIs(self.session.values,values);self.assertEqual(values,[.6,0.,.4])
        self.assertEqual(self.window.state,self.api.state);self.assertEqual(self.window.ctx['weights'],self.api.weights)
        self.assertTrue(self.session.last_stroke['layer_values_verified']);self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)

    def test_missing_or_wrong_receipt_uses_normal_verified_prepare(self):
        provider=self.api.commit_paint
        def wrong(data,scope):receipt=provider(data,scope);receipt['scope']['uuid']='wrong';return receipt
        self.api.commit_paint=wrong;self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.])
        with mock.patch.object(self.session,'prepare',wraps=self.session.prepare) as prepare:self.session.after_stroke()
        self.assertEqual(prepare.call_count,1);self.assertEqual(self.session.values,[.6,0.,0.])

    def test_undo_and_tool_change_cannot_reuse_stale_ui_snapshot(self):
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.]);self.session.after_stroke()
        for name,callback in self.api.callbacks.values():
            if name=='Undo':callback()
        self.assertIsNone(self.session.take_committed_snapshot())
        self.session._committed_snapshot=('sentinel',);self.api.tool='selectSuperContext'
        self.assertIsNone(self.session.take_committed_snapshot())

    def test_receipt_mask_delta_keeps_untouched_values(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.session.before_stroke();self.api.paint_buffer.write([1.,.25,1.]);self.session.after_stroke()
        self.assertEqual(self.session.values,[1.,.25,1.]);self.assertEqual(self.session.paint_events['verified_commit_receipt'],1)

    def test_component_rebind_retains_native_components_and_restores_feedback_without_skin_work(self):
        self.api.object_mode=False;self.api.selected=['mesh.vtx[1]'];self.api.hilited=[]
        class Selection:
            def __init__(self,other=()):self.items=list(other.items) if hasattr(other,'items') else list(other)
            def add(self,name):self.items.append(name)
        def selected(selection):
            self.api.selected=selection.items[:]
            # Reentrant callbacks during native selection edits are display-only.
            self.session.before_stroke();self.session.set_value(1,0,.9)
        self.api.om.MSelectionList=Selection
        self.api.om.MGlobal=types.SimpleNamespace(getActiveSelectionList=lambda:Selection(self.api.selected),setActiveSelectionList=selected)
        self.session._component_mode_dirty=True;self.api.context_settings['colorfeedback']=False
        with (mock.patch.object(self.session,'prepare',side_effect=AssertionError('Rebind prepared skin')),
              mock.patch.object(self.api,'context',side_effect=AssertionError('Rebind read skin')),
              mock.patch.object(self.api.paint_buffer,'write',side_effect=AssertionError('Rebind uploaded array')),
              mock.patch.object(self.session,'reload_feedback',wraps=self.session.reload_feedback) as feedback):
            self.session.keep_paint_in_component_mode();self.session.keep_paint_in_component_mode()
        self.assertEqual(feedback.call_count,1);self.assertTrue(self.api.context_settings['colorfeedback'])
        self.assertEqual(self.api.selected,['mesh.vtx[1]','mesh']);self.assertFalse(self.api.object_mode)
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api.calls,[])

    def test_relax_release_and_queued_ui_refresh_reuse_the_exact_receipt(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.session.layer,joint='b',mode='weights',values={'0':1.,'1':0.}))
        self.api.weights=core.composite(self.api.state);self.session.prepare()
        native_context=self.api.context
        def commit(action,data,scope):
            # The authoring command still reads live skin state. Only a
            # subsequent Session/UI context read is forbidden by this test.
            with mock.patch.object(self.api,'context',native_context):
                self.api.cmds.rtkLayerSkin(action=action,data=json.dumps(data))
            raw=core.encode(self.api.state)
            return dict(scope=dict(scope),state=self.api.state,weights=self.api.weights[:],
                raw_metadata=raw,state_hash=hashlib.sha256(raw.encode()).hexdigest())
        self.api.commit_edit=commit
        from layer_skin_brush_view import BrushController
        widget=ui.QtWidgets.QWidget();widget.show();s=self.session;s.brush=BrushController(s);c=s.brush
        geometry=types.SimpleNamespace(ray=lambda point:((0.,0.,0.),{0:1.}),screen_radius=lambda point:10.,neighbors=lambda v:[1-v])
        viewport=types.SimpleNamespace(widget=widget,geometry=lambda ctx,radius:geometry,feedback=lambda point:False,redraw=lambda **kw:None)
        try:
            c.begin(viewport,(20,20))
            with (mock.patch.object(s,'prepare',side_effect=AssertionError('Second prepare')),
                  mock.patch.object(s,'snapshot',side_effect=AssertionError('Second snapshot')),
                  mock.patch.object(s,'_write_buffer',side_effect=AssertionError('Full buffer reupload')),
                  mock.patch.object(self.api,'context',side_effect=AssertionError('Second context')),
                  mock.patch.object(self.api,'metadata',side_effect=AssertionError('Second metadata'))):
                c.finish();self.window.follow_selection()
            self.assertEqual(s.last_stroke['status'],'saved');self.assertTrue(s.last_stroke['layer_values_verified'])
            self.assertEqual(self.window.state,self.api.state);self.assertEqual(self.window.ctx['weights'],self.api.weights)
        finally:widget.close()

    def test_large_receipt_updates_only_twenty_display_entries(self):
        count=250000;width=8;self.window.stop_paint();ids=['j'+str(i) for i in range(width)]
        weights=core.storage().DenseWeights([1.]+[0.]*(width-1))*count
        state=core.edit(core.create(weights,count,ids,'large-topology'),'add',dict(name='Large'))
        layer=state['layers'][0]['id'];joint=ids[-1];changed={str(100+i):.5 for i in range(20)}
        state=core.edit(state,'paint',dict(layer=layer,joint=joint,mode='weights',values=changed))
        class DisplayValues(list):
            def __iter__(self):raise AssertionError('Full display scan')
            def __setitem__(self,key,value):touched.append(key);return super().__setitem__(key,value)
        touched=[];s=self.session;s.target='meshShape';s.skin='skin';s.layer=layer;s.joint=joint;s.mode='weights'
        s.values=DisplayValues([0.]*count);s._prepared_context=dict(shape='meshShape')
        scope=dict(shape='meshShape',skin='skin',uuid='mesh-id',count=count,ids=ids,topology='large-topology',meta='meta',layer=layer,joint=joint,mode='weights')
        receipt=dict(scope=scope,state=state,weights=weights,state_hash='verified',raw_metadata='verified')
        with mock.patch.object(core,'encode',side_effect=AssertionError('Post-commit encode')):
            self.assertTrue(s._accept_paint_receipt(receipt,scope,changed))
        self.assertEqual(touched,list(range(100,120)));self.assertEqual(s.values[110],.5)


if __name__=='__main__':unittest.main(verbosity=2)
