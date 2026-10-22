"""Operation math, native-array commits and real Qt layout/interaction checks."""
import copy
import json
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_operations as ops
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI

try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    try:from PySide2 import QtCore,QtWidgets
    except ImportError:QtWidgets=None


class OperationMathTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeAPI();self.layer=self.api.layer
        self.state=core.edit(self.api.state,'assign',dict(layer=self.layer,joints=['a','b'],scope=[0,1,2],generated={
            '0':dict(weights=[.25,.75],coverage=.8),'1':dict(weights=[0.,1.],coverage=.4)}))
    def edit(self,operation,amount,mode='weights',vertices=(0,),**data):
        result,dirty,_=ops.edit(self.state,dict(layer=self.layer,mode=mode,joint='a',operation=operation,amount=amount,**data),core,vertices)
        core.validate(result);return result,dirty
    def contribution(self,state,vertex,joint='a'):
        return sessions.Session.layer_values(None,state,self.layer,joint,'weights')[vertex]
    def test_replace_add_scale_use_authored_contribution_including_coverage(self):
        before=copy.deepcopy(self.state)
        for operation,amount,expected in [('replace',.5,.5),('add',.1,.3),('add',-.1,.1),('scale',.5,.1),('scale',2.,.4)]:
            with self.subTest(operation=operation,amount=amount):
                result,dirty=self.edit(operation,amount)
                self.assertAlmostEqual(self.contribution(result,0),expected);self.assertEqual(dirty,[0])
                self.assertEqual(result['layers'][0]['generated'],before['layers'][0]['generated'])
                self.assertEqual(self.contribution(result,1),self.contribution(before,1))
        self.assertEqual(self.state,before)
    def test_operations_clamp_both_ends_and_preserve_normalized_samples(self):
        for operation,amount,expected in [('add',1.,1.),('add',-1.,0.),('scale',100.,1.),('scale',0.,0.)]:
            result,_=self.edit(operation,amount)
            self.assertAlmostEqual(self.contribution(result,0),expected)
            for v in range(3):self.assertAlmostEqual(sum(core.composite(result)[v*2:v*2+2]),1.)
    def test_mask_default_is_one_and_operations_leave_weight_samples_unchanged(self):
        for operation,amount,expected in [('replace',.3,.3),('add',-.2,.8),('scale',.5,.5)]:
            result,dirty=self.edit(operation,amount,'mask',vertices=(1,2))
            self.assertEqual(dirty,[1,2]);self.assertEqual(result['layers'][0]['mask'],{'1':expected,'2':expected})
            self.assertEqual(result['layers'][0]['samples'],self.state['layers'][0]['samples'])
    def test_missing_weight_starts_zero_and_mask_alpha_do_not_multiply_the_operation(self):
        self.state=core.edit(self.state,'paint',dict(layer=self.layer,mode='mask',values={'0':.2}))
        self.state=core.edit(self.state,'properties',dict(layer=self.layer,opacity=.3))
        result,_=self.edit('add',.1,vertices=(0,2))
        self.assertAlmostEqual(self.contribution(result,0),.3);self.assertAlmostEqual(self.contribution(result,2),.1)
        self.assertEqual(result['layers'][0]['mask'],{'0':.2});self.assertEqual(result['layers'][0]['opacity'],.3)
    def test_identity_and_saturated_operations_reuse_state_without_new_overrides(self):
        for operation,amount,vertices in [('add',0.,(0,)),('scale',1.,(0,)),('scale',2.,(2,)),('add',-1.,(2,))]:
            result,dirty=self.edit(operation,amount,vertices=vertices);self.assertIs(result,self.state);self.assertEqual(dirty,[])
    def test_invalid_parameters_and_scope_are_rejected_before_mutation(self):
        before=copy.deepcopy(self.state)
        for operation,amount in [('replace',2.),('add',-2.),('scale',-1.),('scale',float('inf')),('replace',float('nan')),('unknown',.5)]:
            with self.subTest(operation=operation,amount=amount),self.assertRaises(ValueError):self.edit(operation,amount)
        for vertices in [(),(-1,),(3,),(True,)]:
            with self.assertRaises(ValueError):self.edit('replace',.3,vertices=vertices)
        self.assertEqual(self.state,before)
    def test_disabled_layer_saves_values_without_dirty_native_skin_rows(self):
        self.state=core.edit(self.state,'properties',dict(layer=self.layer,enabled=False))
        result,dirty=self.edit('add',.1);self.assertEqual(dirty,[]);self.assertAlmostEqual(self.contribution(result,0),.3)


class OperationArrayTests(unittest.TestCase):
    def setUp(self):self.api=FakeAPI();self.session=sessions.Session(self.api)
    def tearDown(self):self.session.close()
    def test_tool_activation_preferences_do_not_override_chosen_operation(self):
        original=self.api.cmds.setToolTo
        def activate(name):
            original(name);self.api.context_settings.update(selectedattroper='absolute',value=1.)
        self.api.cmds.setToolTo=activate
        self.session.start('mesh',self.api.layer,joint='b',mode='weights',operation='add',value=-.2)
        self.assertEqual(self.api.context_settings['selectedattroper'],'additive');self.assertEqual(self.api.context_settings['value'],-.2)
    def test_native_context_sets_operation_and_value_without_changing_feedback_range(self):
        for operation,amount,native in [('replace',.6,'absolute'),('add',-.2,'additive'),('scale',2.,'scale'),('relax',1.,'absolute')]:
            with self.subTest(operation=operation):
                self.session.start('mesh',self.api.layer,joint='b',mode='weights',operation=operation,value=amount)
                flags=self.api.context_settings
                self.assertEqual(flags['selectedattroper'],native);self.assertEqual(flags['value'],amount)
                self.assertEqual((flags['clamp'],flags['clamplower'],flags['clampupper']),('both',0.,1.))
                self.assertEqual((flags['colorrangelower'],flags['colorrangeupper']),(0.,1.))
                self.assertGreaterEqual(flags['maxvalue'],max(1.,amount));self.assertLessEqual(flags['minvalue'],min(0.,amount))
    def test_native_array_result_is_not_added_or_scaled_again_and_undo_restores_original(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,joint='b',mode='weights',values={'0':.4}))
        self.api.weights=core.composite(self.api.state)
        for operation,amount,after in [('add',.2,.6),('scale',.5,.2),('replace',.3,.3)]:
            with self.subTest(operation=operation):
                self.session.start('mesh',self.api.layer,joint='b',mode='weights',operation=operation,value=amount)
                before=self.api.snapshot();self.session.before_stroke();self.api.paint_buffer.write([after,0.,0.]);self.session.after_stroke()
                self.assertEqual(self.session.values,[after,0.,0.]);self.assertEqual(self.session.last_stroke['operation'],operation)
                self.assertEqual(self.api.calls[-1][1]['values'],{'0':after});self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_native_add_and_scale_mask_results_persist_after_switching_view(self):
        self.session.start('mesh',self.api.layer,mode='mask',operation='add',value=-.2)
        self.session.before_stroke();self.api.paint_buffer.write([.8,1.,1.]);self.session.after_stroke()
        self.session.start('mesh',self.api.layer,joint='b',mode='weights')
        self.session.start('mesh',self.api.layer,mode='mask',operation='scale',value=.5)
        self.assertEqual(self.session.values,[.8,1.,1.])
        self.session.before_stroke();self.api.paint_buffer.write([.4,1.,1.]);self.session.after_stroke()
        self.session.stop();self.session.start('mesh',self.api.layer,mode='mask');self.assertEqual(self.session.values,[.4,1.,1.])


@unittest.skipIf(QtWidgets is None,'PySide is required')
class OperationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        import layer_skin_ui as ui
        from test_layer_skin_ui import Adapter
        self.api=Adapter();self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
        self.window.choose_joint('|b')
    def tearDown(self):self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def row(self):return next(row for row in self.api.state['layers'] if row['id']==self.window.selected_id())
    def test_four_groups_share_row_and_have_parameters_above_aligned_execute_buttons(self):
        w=self.window
        for width in (1280,1040):
            w.resize(width,940);self.app.processEvents()
            groups=[w.operation_groups[name] for name in ('relax','replace','add','scale')]
            self.assertEqual(len({g.y() for g in groups}),1)
            for a,b in zip(groups,groups[1:]):self.assertLess(a.geometry().right(),b.x())
            bottoms=[]
            for name,group in w.operation_groups.items():
                button=w.operation_buttons[name];bottoms.append(button.mapTo(w,QtCore.QPoint()).y())
                controls=[w.relax_iterations,w.relax_strength,w.relax_max_new,w.brush_passes,w.preserve_coverage] if name=='relax' else [w.operation_values[name]]
                for control in controls:
                    self.assertLess(control.mapTo(group,QtCore.QPoint(0,control.height())).y(),button.y())
                    self.assertTrue(group.rect().contains(control.geometry()) if control.parentWidget() is group else True)
                self.assertTrue(group.rect().contains(button.geometry()))
            self.assertEqual(len(set(bottoms)),1)
            scroll=w.dock_layout.centralWidget();self.assertLessEqual(scroll.widget().width(),scroll.viewport().width())
            self.assertGreaterEqual(w.relax_max_new.lineEdit().width(),w.relax_max_new.fontMetrics().horizontalAdvance('Unlimited')+4)
    def test_independent_values_and_radios_drive_native_brush_settings(self):
        w=self.window;w.value.setValue(.7);w.add_value.setValue(-.2);w.scale_value.setValue(2.)
        w.paint()
        for name,amount,native in [('add',-.2,'additive'),('scale',2.,'scale'),('replace',.7,'absolute'),('relax',1.,'absolute')]:
            w.operation_radios[name].setChecked(True)
            self.assertEqual(w.session.brush_operation,name);self.assertEqual(self.api.context_settings['value'],amount)
            self.assertEqual(self.api.context_settings['selectedattroper'],native)
        self.assertEqual((w.value.value(),w.add_value.value(),w.scale_value.value()),(.7,-.2,2.))
    def test_inactive_group_parameter_does_not_change_active_brush(self):
        w=self.window;w.paint();w.add_value.setValue(.3);w.add_value.editingFinished.emit()
        self.assertEqual(self.api.context_settings['value'],1.);self.assertEqual(w.session.brush_operation,'replace')
        w.operation_radios['add'].setChecked(True);w.add_value.setValue(-.1);w.add_value.editingFinished.emit()
        self.assertEqual(self.api.context_settings['value'],-.1)
    def test_native_radius_and_operation_value_sync_to_correct_group(self):
        w=self.window;w.value.setValue(.6);w.paint();w.operation_radios['scale'].setChecked(True)
        self.api.context_settings.update(value=1.75,radius=4.,opacity=.4);w.sync_brush_settings()
        self.assertEqual((w.value.value(),w.scale_value.value(),w.brush_radius.value(),w.brush_opacity.value()),(.6,1.75,4.,.4))
        w.operation_radios['relax'].setChecked(True);self.api.context_settings['value']=.1;w.sync_brush_settings()
        self.assertEqual(w.scale_value.value(),1.75)
    def test_execute_operations_apply_full_value_on_vertices_and_are_individually_undoable(self):
        w=self.window;self.api.selected=['mesh.vtx[1]'];w.value.setValue(.4)
        for name,field,value,expected in [('replace',w.value,.4,.4),('add',w.add_value,.2,.6),('scale',w.scale_value,.5,.3)]:
            field.setValue(value);before=self.api.snapshot();self.assertTrue(w.execute_operation(name))
            actual=w.session.layer_values(self.api.state,w.selected_id(),'b','weights')
            self.assertAlmostEqual(actual[1],expected);self.assertEqual([actual[0],actual[2]],[0.,0.])
            self.assertEqual(w._brush_operation,name);self.api.undo();self.assertEqual(self.api.snapshot(),before);self.api.redo()
        self.assertEqual(self.api.selected,['mesh.vtx[1]']);self.assertTrue(self.api.weight_view.visible)
    def test_whole_mesh_mask_uses_operation_without_a_joint_and_preserves_weight_samples(self):
        w=self.window;w.paint_mode.setCurrentIndex(1);w.whole.setChecked(True);w._active_joint=None;w._active_joint_path=None
        w.add_value.setValue(-.2);before=copy.deepcopy(self.row()['samples'])
        self.assertTrue(w.execute_operation('add'));row=self.row()
        self.assertEqual(row['mask'],{'0':.8,'1':.8,'2':.8});self.assertEqual(row['samples'],before)
    def test_execute_requires_explicit_scope_and_rejects_without_scene_changes(self):
        w=self.window;before=self.api.snapshot();self.assertFalse(w.execute_operation('replace'))
        self.assertEqual(self.api.snapshot(),before);self.assertIn('Select mesh vertices',w.status.text())
    def test_changing_operation_commits_pending_array_once_before_native_mode_changes(self):
        w=self.window;w.paint();w.session.before_stroke();self.api.paint_buffer.write([.3,0.,0.])
        w.operation_radios['add'].setChecked(True);w.session.after_stroke()
        self.assertEqual(len(self.api.calls),1);self.assertEqual(w.session.values,[.3,0.,0.])
        self.assertEqual(w.session.last_stroke['operation'],'replace');self.assertEqual(w.session.brush_operation,'add')
    def test_rejected_pending_stroke_restores_previous_operation_and_radio(self):
        w=self.window;w.paint();w.session.before_stroke();self.api.paint_buffer.write([.3,0.,0.]);before=self.api.snapshot();self.api.fail=True
        w.operation_radios['add'].setChecked(True)
        self.assertEqual(w._brush_operation,'replace');self.assertTrue(w.operation_radios['replace'].isChecked());self.assertEqual(self.api.snapshot(),before)
    def test_execute_during_brushing_resumes_the_matching_operation(self):
        w=self.window;w.whole.setChecked(True);w.paint();w.add_value.setValue(.2)
        self.assertTrue(w.execute_operation('add'));self.assertTrue(w.session.active)
        self.assertEqual(w.session.brush_operation,'add');self.assertEqual(self.api.context_settings['selectedattroper'],'additive')
        self.assertEqual(w.session.values,[.2]*3)
    def test_execute_binds_an_unweighted_joint_at_zero_and_undo_restores_binding_and_layers(self):
        w=self.window;w.choose_joint('|c');w.whole.setChecked(True);w.value.setValue(.5)
        before=self.api.snapshot();self.assertTrue(w.execute_operation('replace'))
        self.assertEqual(self.api.ids,['a','b','c']);self.assertEqual(w.session.values,[.5]*3)
        self.assertEqual(len(self.api.undo_stack),1);self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_relax_execute_stops_after_a_pending_stroke_is_rejected(self):
        w=self.window;w.paint();w.session.before_stroke();self.api.paint_buffer.write([.3,0.,0.]);self.api.fail=True
        before=self.api.snapshot();self.assertFalse(w.relax())
        self.assertEqual(w._brush_operation,'replace');self.assertEqual(self.api.snapshot(),before)
        self.assertTrue(all(action!='relax' for action,data in self.api.calls))
    def test_relax_execute_in_mask_mode_smooths_mask_and_leaves_layer_weights_unchanged(self):
        w=self.window;w.run('paint',dict(mode='mask',values={'0':0.}));w.paint_mode.setCurrentIndex(1)
        self.api.selected=['mesh.vtx[0]'];w.relax_iterations.setValue(1);w.relax_strength.setValue(.5)
        before=copy.deepcopy(self.row()['samples']);self.assertTrue(w.relax())
        self.assertEqual(self.row()['mask'],{'0':.5});self.assertEqual(self.row()['samples'],before)
        self.assertEqual(w._brush_operation,'relax')
    def test_warm_refresh_preserves_all_values_active_operation_and_undo_history(self):
        import layer_skin_ui_refresh as refresh
        w=self.window;w.value.setValue(.7);w.add_value.setValue(-.25);w.scale_value.setValue(1.8)
        w.operation_radios['scale'].setChecked(True);w.paint();self.api.context_settings['value']=2.5
        before=self.api.snapshot();history=list(self.api.undo_stack)
        self.window=refresh.refresh(w);w=self.window
        self.assertEqual(w._brush_operation,'scale');self.assertEqual((w.value.value(),w.add_value.value(),w.scale_value.value()),(.7,-.25,2.5))
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,history)
        w.paint();self.assertEqual(self.api.context_settings['selectedattroper'],'scale');self.assertEqual(self.api.context_settings['value'],2.5)


if __name__=='__main__':unittest.main()
