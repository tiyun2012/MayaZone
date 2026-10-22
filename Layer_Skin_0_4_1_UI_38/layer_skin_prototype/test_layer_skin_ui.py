"""Real Qt interactions with a pure Python command adapter, not a Maya emulator."""
import copy
import json
import types
import unittest
from unittest import mock
import layer_skin_core as core

try:
    import layer_skin_ui as ui
    from PySide6 import QtCore, QtWidgets, QtTest
except ImportError:
    try:
        import layer_skin_ui as ui
        from PySide2 import QtCore, QtWidgets, QtTest
    except ImportError:
        ui = None


from test_layer_skin_session import FakeAPI


class Adapter(FakeAPI):
    def __init__(self):
        super(Adapter,self).__init__()
        self.state=core.create(self.weights,3,self.ids,'topology')
        for name in ['Base correction','Elbow','Shoulder']:
            self.state=core.edit(self.state,'add',{'name':name})
            self.state=core.edit(self.state,'membership',dict(layer=self.state['layers'][-1]['id'],joints=['a','b']))
        self.api=self


class JointSceneAPI(Adapter):
    """Maya DAG queries only; the product creates its real Qt hierarchy widget."""
    def __init__(self):
        super(JointSceneAPI,self).__init__()
        self.joint_paths=['|joint1','|joint1|joint2','|joint1|joint2|joint3']
        self.path_ids={path:'joint-id-'+str(i) for i,path in enumerate(self.joint_paths)}
        self.ids=[self.path_ids[path] for path in self.joint_paths];self.weights=[1.,0.,0.]*3
        self.state=core.edit(core.create(self.weights,3,self.ids,'topology'),'add',dict(name='Working'))
        self.layer=self.state['layers'][0]['id']
        self.state=core.edit(self.state,'membership',dict(layer=self.layer,joints=self.ids))
        self.cmds.objExists=lambda path:path in self.joint_paths
        self.cmds.nodeType=lambda node:'joint' if node in self.joint_paths else ('transform' if node.startswith('|') else self.node_type(node))
        self.cmds.getAttr=lambda plug:False
        self.om.MFnDependencyNode=lambda node:types.SimpleNamespace(isLocked=False,uuid=lambda:types.SimpleNamespace(asString=lambda:self.path_ids.get(node,str(node).split('|')[-1])))
        self.make_joint_tree=self.real_joint_tree
    def real_joint_tree(self,parent,selected):
        from layer_skin_joint_view import JointTree
        from layer_skin_session import protect_browser_widget
        return JointTree(self,parent,selected,protect_browser_widget)
    def make_session(self):
        from layer_skin_session import Session
        return Session(self)
    def roots(self,ctx):return ['|joint1']
    def joint_id(self,path):return self.path_ids[path]
    def context(self,target):
        ctx=super(JointSceneAPI,self).context(target)
        by_id={self.path_ids[path]:path for path in self.joint_paths}
        ctx['influences']=[types.SimpleNamespace(fullPathName=lambda path=by_id[identity]:path) for identity in self.ids]
        return ctx
    def relatives(self,node,**kw):
        if kw.get('allDescendents'):return list(reversed([path for path in self.joint_paths if path.startswith(node+'|')]))
        return super(JointSceneAPI,self).relatives(node,**kw)


@unittest.skipIf(ui is None,'PySide is required for joint hierarchy checks')
class SceneJointTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.api=JointSceneAPI();self.window=ui.LayerUI(self.api)
        self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def set_skin(self,paths):
        self.api.ids=[self.api.path_ids[path] for path in paths]
        self.api.weights=([1.]+[0.]*(len(paths)-1))*3
        self.api.state=core.edit(core.create(self.api.weights,3,self.api.ids,'topology'),'add',dict(name='Working'))
        self.api.layer=self.api.state['layers'][0]['id']
        self.window.refresh()
    def test_only_tip_influence_still_shows_the_full_ancestor_chain(self):
        self.window._active_joint=None;self.window._active_joint_path=None
        tip=self.api.joint_paths[-1];self.set_skin([tip]);browser=self.window.browser
        self.assertEqual(set(browser.items),set(self.api.joint_paths));self.assertEqual(browser.roots,('|joint1',))
        self.assertEqual(browser.joints(),[tip]);self.assertEqual(self.api.selected,['mesh'])
        self.assertEqual(browser.widget.topLevelItem(0).child(0).child(0).text(0),'joint3')
    def test_every_skin_root_is_visible_together_and_unrelated_skeleton_is_excluded(self):
        added=['|rigB|rootB','|rigB|rootB|joint2','|unrelated|otherJoint']
        for i,path in enumerate(added):self.api.joint_paths.append(path);self.api.path_ids[path]='added-'+str(i)
        self.set_skin([self.api.joint_paths[2],added[1]])
        browser=self.window.browser
        self.assertEqual(browser.widget.topLevelItemCount(),2)
        self.assertEqual(set(browser.items),set(self.api.joint_paths)-{added[2]})
        self.assertEqual(browser.items[added[1]].parent().text(0),'rootB')
        self.assertEqual(browser.records[added[1]],'added-1')
    def test_transform_buffer_does_not_split_a_joint_ancestor_branch(self):
        path='|joint1|joint2|buffer|tip';self.api.joint_paths.append(path);self.api.path_ids[path]='tip'
        self.set_skin([path]);browser=self.window.browser
        self.assertEqual(browser.roots,('|joint1',));self.assertEqual(browser.widget.topLevelItemCount(),1)
        self.assertEqual(browser.items[path].parent().text(0),'joint2')
        self.assertNotIn('|joint1|joint2|buffer',browser.items)
    def test_zero_weight_influence_and_unbound_descendant_remain_gray_and_selectable(self):
        path='|joint1|joint2|joint3|unbound';self.api.joint_paths.append(path);self.api.path_ids[path]='unbound'
        self.window.refresh(force_browser=True);browser=self.window.browser
        for candidate in (self.api.joint_paths[1],path):
            item=browser.items[candidate]
            self.assertTrue(browser.styling.delegates[0].is_empty(browser.widget.indexFromItem(item)))
            browser.select_joint(candidate);self.assertEqual(browser.joints(),[candidate])
        self.assertNotIn('unbound',self.api.ids)
    def test_renamed_influence_rebuilds_automatically_and_preserves_uuid_selection(self):
        old=self.api.joint_paths[-1];identity=self.api.path_ids[old];self.window.choose_joint(old)
        path=old.rsplit('|',1)[0]+'|renamedTip';self.api.joint_paths[-1]=path
        self.api.path_ids[path]=self.api.path_ids.pop(old);self.window.refresh()
        self.assertNotIn(old,self.window.browser.items);self.assertEqual(self.window.browser.joints(),[path])
        self.assertEqual(self.window.active_joint(),identity);self.assertEqual(self.window._active_joint_path,path)
    def test_new_influence_root_preserves_existing_collapsed_branch_and_selected_joint(self):
        browser=self.window.browser;middle=self.api.joint_paths[1];self.window.choose_joint(middle)
        browser.items['|joint1'].setExpanded(False)
        path='|rigB|rootB';self.api.joint_paths.append(path);self.api.path_ids[path]='root-b'
        self.set_skin(self.api.joint_paths)
        self.assertEqual(browser.widget.topLevelItemCount(),2);self.assertFalse(browser.items['|joint1'].isExpanded())
        self.assertEqual(browser.joints(),[middle]);self.assertTrue(browser.items[path].isExpanded())
    def test_selecting_a_scene_joint_does_not_crop_other_skin_branches(self):
        before=set(self.window.browser.items);self.api.selected=[self.api.joint_paths[-1]]
        self.window.follow_selection();self.assertEqual(set(self.window.browser.items),before)
        self.assertEqual(self.window.browser.roots,('|joint1',))
    def test_recreated_joint_at_the_same_path_uses_its_new_identity(self):
        path=self.api.joint_paths[-1];old=self.api.path_ids[path];self.window.choose_joint(path)
        self.api.path_ids[path]='new-tip';self.set_skin([path])
        self.assertEqual(self.window.browser.records[path],'new-tip');self.assertNotIn(old,self.window.browser.records.values())
        self.assertEqual(self.window.active_joint(),'new-tip')
    def test_warm_refresh_replaces_the_loaded_native_joint_tree_helper(self):
        import layer_skin_ui_refresh as refresh_ui
        owner={'VERSION':self.api.VERSION,'WINDOW':self.api.WINDOW,'_ui_module':object(),
            '_modules':{'layer_skin_joint_view':types.SimpleNamespace(JointTree=mock.Mock(side_effect=AssertionError('old tree reused')))},
            'old_factory':self.api.make_session}
        exec('def make_session():\n    return old_factory()\n',owner);self.api.make_session=owner['make_session']
        self.api.make_joint_tree=lambda parent,selected:owner['_modules']['layer_skin_joint_view'].JointTree(self.api,parent,selected)
        before=self.api.snapshot();self.window=refresh_ui.refresh(self.window);self.app.processEvents()
        self.assertIs(type(self.window.browser),owner['_modules']['layer_skin_joint_view'].JointTree)
        self.assertEqual(set(self.window.browser.items),set(self.api.joint_paths));self.assertEqual(self.api.snapshot(),before)
    def test_product_tree_shows_joint1_joint2_joint3_with_actual_parent_child_rows(self):
        browser=self.window.browser;tree=browser.widget
        self.assertTrue(tree.isVisible());self.assertEqual(tree.topLevelItemCount(),1)
        root=tree.topLevelItem(0);self.assertEqual(root.text(0),'joint1')
        second=root.child(0);third=second.child(0)
        self.assertEqual(second.text(0),'joint2');self.assertEqual(third.text(0),'joint3')
        self.assertTrue(root.isExpanded());self.assertTrue(second.isExpanded())
        self.assertGreater(tree.visualItemRect(third).height(),0)
        self.assertFalse(root.icon(0).isNull());self.assertFalse(browser.empty.isVisible())
    def test_clicking_a_real_hierarchy_row_sets_the_paint_target_without_scene_selection(self):
        browser=self.window.browser;path=self.api.joint_paths[2];item=browser.items[path]
        before=list(self.api.selected)
        QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
        self.assertEqual(self.window.active_joint(),self.api.path_ids[path]);self.assertEqual(self.api.selected,before)
        self.window.paint();self.assertEqual(self.window.session.joint,self.api.path_ids[path])
    def test_unweighted_rows_stay_visible_and_weighted_rows_update_after_paint(self):
        browser=self.window.browser;path=self.api.joint_paths[2];identity=self.api.path_ids[path]
        index=browser.widget.indexFromItem(browser.items[path]);delegate=browser.styling.delegates[0]
        self.assertTrue(delegate.is_empty(index))
        self.window.choose_joint(path);self.window.paint();self.window.session.initialize('meshShape')
        self.window.session.set_value(1,0,1.);self.window.session.finalize(1);self.app.processEvents()
        self.assertFalse(delegate.is_empty(browser.widget.indexFromItem(browser.items[path])))
        self.assertEqual(browser.widget.topLevelItemCount(),1)
    def test_real_joint_click_roundtrip_restores_painted_values_and_selection(self):
        browser=self.window.browser;path=self.api.joint_paths[2];other=self.api.joint_paths[1]
        def click(joint):
            item=browser.items[joint]
            QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
            self.app.processEvents()
        click(path);self.window.paint();session=self.window.session
        session.before_stroke();session.set_value(1,0,.8);session.after_stroke();self.app.processEvents()
        saved=self.api.snapshot();click(other);self.assertEqual(session.values,[0.]*3)
        click(path);self.assertEqual(session.values,[.8,0.,0.]);self.assertEqual(browser.joints(),[path])
        self.assertEqual(self.api.snapshot(),saved);self.assertTrue(session.active)
        self.assertIn('0.80',self.window.display_range.text())
    def test_native_array_joint_click_roundtrip_reloads_full_view_data(self):
        browser=self.window.browser;path=self.api.joint_paths[2];other=self.api.joint_paths[1]
        self.window.choose_joint(path);self.window.paint();session=self.window.session
        session.before_stroke();self.api.paint_buffer.write([.8,0.,.3]);session.after_stroke()
        self.app.processEvents()
        def click(joint):
            item=browser.items[joint]
            QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
            self.app.processEvents()
        click(other);self.assertEqual(session.buffer.read(),[0.]*3)
        click(path);self.assertEqual(session.buffer.read(),[.8,0.,.3])
        self.assertIn('0.80',self.window.display_range.text())
        self.assertEqual(session.paint_events.get('set_value',0),0)
    def test_array_release_timer_waits_then_commits_without_scalar_samples(self):
        self.window.choose_joint(self.api.joint_paths[2]);self.window.paint();session=self.window.session
        held=[True];self.window.brush_button_held=lambda:held[0]
        session.before_stroke();self.api.paint_buffer.write([.6,.2,0.])
        QtTest.QTest.qWait(50)
        self.assertTrue(self.window._paint_timer.isActive());self.assertEqual(self.api.calls,[])
        self.assertEqual(session.stroke['values'],{})
        held[0]=False;QtTest.QTest.qWait(70)
        self.assertEqual(len(self.api.calls),1);self.assertEqual(session.values,[.6,.2,0.])
        self.assertEqual(session.last_stroke['commit_reason'],'mouse_release_fallback')
        self.assertEqual(self.api._chunk_depth,0)
    def test_real_joint_click_saves_samples_even_if_native_stroke_callbacks_are_missing(self):
        browser=self.window.browser;path=self.api.joint_paths[2];other=self.api.joint_paths[1]
        self.window.choose_joint(path);self.window.paint();session=self.window.session
        QtTest.QTest.mousePress(self.window,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,QtCore.QPoint(1,1))
        try:session.set_value(1,0,.8)
        finally:QtTest.QTest.mouseRelease(self.window,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,QtCore.QPoint(1,1))
        item=browser.items[other]
        QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
        self.assertEqual(session.joint,self.api.path_ids[other]);self.assertEqual(len(self.api.undo_stack),1)
        self.window.choose_joint(path);self.assertEqual(session.values,[.8,0.,0.])
        self.assertEqual(session.last_stroke['joint'],self.api.path_ids[path])
        self.assertEqual(session.last_stroke['commit_reason'],'action_change')
    def test_real_hierarchy_can_paint_a_joint_that_is_not_in_the_layer_yet(self):
        self.api.state=core.edit(self.api.state,'membership',dict(layer=self.api.layer,joints=[]));self.window.refresh()
        browser=self.window.browser;path=self.api.joint_paths[2];item=browser.items[path]
        QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
        self.window.paint();self.assertEqual(self.api.state['layers'][0]['joints'],[])
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.6);self.window.session.finalize(1)
        self.app.processEvents()
        self.assertEqual(self.api.state['layers'][0]['joints'],[self.api.path_ids[path]])
        self.assertFalse(browser.styling.delegates[0].is_empty(browser.widget.indexFromItem(browser.items[path])))
    def test_rejected_then_saved_stroke_retains_real_joint_selection_and_feedback_values(self):
        import layer_skin_session as paint
        browser=self.window.browser;path=self.api.joint_paths[2];identity=self.api.path_ids[path]
        self.window.choose_joint(path);self.window.paint();layer=self.window.selected_id()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.8)
        self.api.fail=True;paint.dispatch('finalize',1);self.app.processEvents()
        self.assertIn('Stroke rejected',self.window.status.text());self.assertEqual(browser.joints(),[path])
        self.assertEqual(self.window.session.get_value(1,0),0.)
        self.api.fail=False;self.window.session.before_stroke();self.window.session.set_value(1,0,.8)
        self.window.session.after_stroke();self.app.processEvents()
        self.assertIn('Stroke saved',self.window.status.text());self.assertEqual(self.window.active_joint(),identity)
        self.assertEqual(self.window.selected_id(),layer);self.assertEqual(browser.joints(),[path])
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.session.get_value(1,0),.8)
        self.assertFalse(browser.styling.delegates[0].is_empty(browser.widget.indexFromItem(browser.items[path])))
        self.window.session.before_stroke();self.window.session.set_value(1,1,.7)
        self.window.session.finalize(1);self.window.session.after_stroke();self.app.processEvents()
        self.assertEqual(self.window.session.values,[.8,.7,0.]);self.assertEqual(len(self.api.undo_stack),2)
        self.assertEqual(browser.joints(),[path]);self.assertEqual(self.api.selected,['mesh'])
    def test_real_hierarchy_unbound_joint_binds_only_when_the_first_stroke_commits(self):
        path='|joint1|joint2|unbound';identity='unbound-id'
        self.api.joint_paths.append(path);self.api.path_ids[path]=identity;self.window.refresh(force_browser=True)
        browser=self.window.browser;item=browser.items[path]
        QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,browser.widget.visualItemRect(item).center())
        self.window.paint();self.assertTrue(self.window.session.active);self.assertNotIn(identity,self.api.ids)
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.6);self.window.session.finalize(1)
        self.app.processEvents()
        self.assertIn(identity,self.api.ids);self.assertEqual(len(self.api.undo_stack),1)
        self.assertFalse(browser.styling.delegates[0].is_empty(browser.widget.indexFromItem(browser.items[path])))
    def test_selected_assignment_preserves_real_hierarchy_multi_selection(self):
        tree=self.window.browser.widget;paths=self.api.joint_paths[1:]
        for i,path in enumerate(paths):
            item=self.window.browser.items[path]
            QtTest.QTest.mouseClick(tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.ControlModifier if i else QtCore.Qt.NoModifier,tree.visualItemRect(item).center())
        self.assertTrue(self.window.assign());self.app.processEvents()
        self.assertEqual(set(self.window.browser.joints()),set(paths))
        self.assertEqual(set(self.api.calls[-1][1]['joints']),{self.api.path_ids[path] for path in paths})
    def test_refresh_preserves_collapsed_branches_and_selection(self):
        browser=self.window.browser;path=self.api.joint_paths[1]
        self.window.choose_joint(path);browser.items[path].setExpanded(False)
        self.window.refresh(force_browser=True)
        self.assertFalse(browser.items[path].isExpanded());self.assertEqual(browser.joints(),[path])
    def test_intermediate_transforms_do_not_flatten_joint_hierarchy(self):
        path='|joint1|joint2|buffer|joint4';self.api.joint_paths.append(path);self.api.path_ids[path]='four'
        self.window.refresh(force_browser=True);item=self.window.browser.items[path]
        self.assertEqual(item.parent().text(0),'joint2')
    def test_invalid_root_shows_an_explanation_in_the_dock(self):
        browser=self.window.browser;browser.scope('|missing')
        self.assertEqual(browser.widget.topLevelItemCount(),0);self.assertTrue(browser.empty.isVisible())
        self.assertIn('No joints found',browser.empty.text())
    def test_tree_selection_remains_separate_from_vertex_selection(self):
        self.api.selected=['mesh.vtx[0]'];self.window.browser.select_joint(self.api.joint_paths[1])
        self.assertEqual(self.api.selected,['mesh.vtx[0]'])
    def test_destroying_the_window_releases_the_actual_tree(self):
        browser=self.window.browser;widget=browser.widget;self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertTrue(browser.closed);self.assertIsNone(browser.widget);self.assertFalse(ui.shiboken.isValid(widget))
    def test_failed_browser_creation_is_visible_and_can_be_retried(self):
        from unittest import mock
        self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.api.make_joint_tree=mock.Mock(side_effect=RuntimeError('tree creation test'))
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.app.processEvents()
        self.assertIsNone(self.window.browser);self.assertTrue(self.window.browser_error.isVisible())
        self.assertIn('tree creation test',self.window.browser_error.text())
        self.api.make_joint_tree=self.api.real_joint_tree;self.window.refresh(force_browser=True)
        self.assertFalse(self.window.browser_error.isVisible());self.assertEqual(self.window.browser.widget.topLevelItemCount(),1)
    def test_partial_tree_creation_failure_does_not_leave_an_extra_empty_tree(self):
        from unittest import mock
        import layer_skin_joint_view
        self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        with mock.patch.object(layer_skin_joint_view,'JointStyling',side_effect=RuntimeError('style test')):
            self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.app.processEvents()
            self.assertIsNone(self.window.browser);self.assertTrue(self.window.browser_error.isVisible())
            self.assertTrue(all(not tree.isVisible() for tree in self.window.browser_host.findChildren(QtWidgets.QTreeWidget)))
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete);self.window.refresh(force_browser=True)
        self.assertEqual(len(self.window.browser_host.findChildren(QtWidgets.QTreeWidget)),1)


@unittest.skipIf(ui is None,'PySide is required for real Qt checks')
class LayerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.adapter=Adapter();self.window=ui.LayerUI(self.adapter.api)
        self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.processEvents()
    def item(self,index=0):return self.window.layers.topLevelItem(index)
    def alpha(self,index=0):
        tree=self.window.layers
        return tree.indexWidget(tree.indexFromItem(self.item(index),3))
    def drop(self,identity,position,source=None):
        tree=self.window.layers;mime=QtCore.QMimeData();mime.setData(tree.MIME,identity.encode())
        event=types.SimpleNamespace(source=lambda:tree if source is None else source,mimeData=lambda:mime,
            position=lambda:QtCore.QPointF(position),accepted=False)
        event.acceptProposedAction=lambda:setattr(event,'accepted',True)
        event.ignore=lambda:setattr(event,'accepted',False)
        tree.dropEvent(event);self.app.processEvents();return event
    def test_paint_info_button_reports_context_without_stopping_or_committing_a_stroke(self):
        import contextlib
        import io
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.3)
        stroke=copy.deepcopy(self.window.session.stroke);calls=len(self.adapter.calls)
        button=next(button for button in self.window.findChildren(QtWidgets.QPushButton) if button.text()=='Paint info')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):button.click()
        self.assertIn('"active_context": "'+self.adapter.paint_context+'"',output.getvalue())
        self.assertIn('"registered_plugin"',output.getvalue());self.assertIn('Script Editor',self.window.status.text())
        self.assertEqual(self.window.session.stroke,stroke);self.assertEqual(len(self.adapter.calls),calls)
        self.assertTrue(self.window.session.active)
    def test_four_columns_and_float_editors(self):
        tree=self.window.layers
        self.assertEqual([tree.headerItem().text(i) for i in range(4)],['↕','Layer name','Enabled','Alpha'])
        self.assertEqual(self.item().text(1),'Shoulder');self.assertIsInstance(self.alpha(),QtWidgets.QDoubleSpinBox)
        self.assertEqual((self.alpha().minimum(),self.alpha().maximum()),(0.,1.))
    def test_refresh_emits_no_scene_commands(self):
        self.window.refresh();self.window.refresh();self.app.processEvents();self.assertEqual(self.adapter.calls,[])
    def test_inline_name_change_is_one_identity_based_command(self):
        identity=self.window.layers.identity(self.item());self.item().setText(1,'Shoulder fix')
        self.assertEqual(len(self.adapter.calls),1);action,data=self.adapter.calls[0]
        self.assertEqual((action,data['layer'],data['name']),('properties',identity,'Shoulder fix'))
        self.assertEqual(self.adapter.state['layers'][-1]['name'],'Shoulder fix')
    def test_empty_name_is_rejected_and_display_restored(self):
        self.item().setText(1,'   ')
        self.assertEqual(self.item().text(1),'Shoulder');self.assertEqual(self.adapter.calls,[])
        self.assertIn('cannot be empty',self.adapter.warnings[-1])
    def test_enabled_checkbox_commits_once_and_undo_restores_it(self):
        self.item().setCheckState(2,QtCore.Qt.Unchecked)
        self.assertFalse(self.adapter.state['layers'][-1]['enabled']);self.assertEqual(len(self.adapter.calls),1)
        self.window.history(False);self.assertEqual(self.item().checkState(2),QtCore.Qt.Checked)
        self.window.history(True);self.assertEqual(self.item().checkState(2),QtCore.Qt.Unchecked)
    def test_alpha_waits_for_commit_and_undo_refreshes_editor(self):
        editor=self.alpha();editor.setValue(.375);self.assertEqual(self.adapter.calls,[])
        editor.editingFinished.emit();self.app.processEvents()
        self.assertEqual(self.adapter.state['layers'][-1]['opacity'],.375);self.assertEqual(len(self.adapter.calls),1)
        self.window.history(False);self.assertEqual(self.alpha().value(),1.)
        self.window.history(True);self.assertEqual(self.alpha().value(),.375)
    def test_unchanged_alpha_does_not_add_undo(self):
        self.alpha().editingFinished.emit();self.assertEqual(self.adapter.calls,[])
    def test_unedited_high_precision_alpha_is_not_rounded_in_scene(self):
        self.adapter.state['layers'][-1]['opacity']=.123456789
        self.window.refresh();self.alpha().editingFinished.emit()
        self.assertEqual(self.adapter.calls,[])
        self.assertEqual(self.adapter.state['layers'][-1]['opacity'],.123456789)
    def test_alpha_enter_commits_once_without_closing_window(self):
        editor=self.alpha();editor.setFocus();editor.selectAll()
        QtTest.QTest.keyClicks(editor,'0.625');QtTest.QTest.keyClick(editor,QtCore.Qt.Key_Return)
        self.app.processEvents();self.assertEqual(self.adapter.state['layers'][-1]['opacity'],.625)
        self.assertEqual(len(self.adapter.calls),1);self.assertTrue(self.window.isVisible())
    def test_drag_move_shows_insertion_line_and_leave_clears_it(self):
        tree=self.window.layers;mime=QtCore.QMimeData();mime.setData(tree.MIME,tree.order()[0].encode())
        event=types.SimpleNamespace(source=lambda:tree,mimeData=lambda:mime,position=lambda:QtCore.QPointF(15,0),
            acceptProposedAction=lambda:None,ignore=lambda:None)
        tree.dragMoveEvent(event);self.app.processEvents();self.assertEqual(tree._drop_slot,0)
        tree.dragLeaveEvent(types.SimpleNamespace(accept=lambda:None));self.assertIsNone(tree._drop_slot)
    def test_failed_alpha_write_restores_value(self):
        self.adapter.fail=True;self.alpha().setValue(.25);self.alpha().editingFinished.emit();self.app.processEvents()
        self.assertEqual(self.alpha().value(),1.);self.assertEqual(self.adapter.undo_stack,[])
    def test_context_menu_rename_opens_name_editor(self):
        menu=self.window.layers.menu_for(self.item());self.assertEqual(next(action.text() for action in menu.actions() if action.text()=='Rename'),'Rename')
        next(action for action in menu.actions() if action.text()=='Rename').trigger();self.app.processEvents()
        editors=self.window.layers.findChildren(QtWidgets.QLineEdit)
        names=[editor for editor in editors if not isinstance(editor.parent(),QtWidgets.QDoubleSpinBox)]
        self.assertTrue(any(editor.text()=='Shoulder' for editor in names));self.assertEqual(self.adapter.calls,[])
        menu.deleteLater()
    def test_double_click_name_opens_editor_without_scene_write(self):
        tree=self.window.layers;rect=tree.visualItemRect(self.item())
        point=QtCore.QPoint(tree.columnViewportPosition(1)+40,rect.center().y())
        QtTest.QTest.mouseClick(tree.viewport(),QtCore.Qt.LeftButton,pos=point)
        QtTest.QTest.mouseDClick(tree.viewport(),QtCore.Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.adapter.calls,[])
        self.assertTrue(any(editor.text()=='Shoulder' for editor in tree.findChildren(QtWidgets.QLineEdit)))
    def test_drop_top_to_bottom_is_one_command_and_undoable(self):
        tree=self.window.layers;before=tree.order()[:-1];position=QtCore.QPoint(20,tree.visualItemRect(self.item(2)).bottom()+8)
        event=self.drop(before[0],position);self.assertTrue(event.accepted)
        expected=before[1:]+before[:1];self.assertEqual(tree.order(),expected+[ui.BASE]);self.assertEqual(len(self.adapter.calls),1)
        self.assertEqual(self.adapter.calls[0][0],'reorder');self.assertEqual(self.adapter.calls[0][1]['order'],list(reversed(expected)))
        self.window.history(False);self.assertEqual(tree.order(),before+[ui.BASE])
        self.window.history(True);self.assertEqual(tree.order(),expected+[ui.BASE])
    def test_drop_bottom_to_top_and_no_nesting(self):
        tree=self.window.layers;before=tree.order()[:-1];self.drop(before[-1],QtCore.QPoint(15,0))
        self.assertEqual(tree.order(),before[-1:]+before[:-1]+[ui.BASE]);self.assertEqual(tree.topLevelItemCount(),4)
        self.assertTrue(all(tree.topLevelItem(i).childCount()==0 for i in range(3)))
    def test_drop_same_slot_does_not_create_undo(self):
        self.drop(self.window.layers.order()[0],QtCore.QPoint(15,0));self.assertEqual(self.adapter.calls,[])
    def test_foreign_and_stale_drags_are_rejected(self):
        tree=self.window.layers;before=tree.order()
        self.assertFalse(self.drop(before[0],QtCore.QPoint(15,0),object()).accepted)
        self.assertFalse(self.drop('missing',QtCore.QPoint(15,0)).accepted)
        self.assertEqual(tree.order(),before);self.assertEqual(self.adapter.calls,[])
    def test_failed_reorder_keeps_authoritative_rows_and_editors(self):
        tree=self.window.layers;before=tree.order();self.adapter.fail=True
        self.drop(before[-2],QtCore.QPoint(15,0));self.assertEqual(tree.order(),before)
        self.assertEqual(self.alpha().value(),1.);self.assertEqual(self.adapter.undo_stack,[])
    def test_controls_do_not_default_to_weight_edit_on_enter(self):
        self.assertFalse(self.window.whole.isChecked())
        self.assertTrue(all(not button.autoDefault() for button in self.window.findChildren(QtWidgets.QPushButton)))
    def test_duplicate_names_keep_correct_identity_after_reorder(self):
        for row in self.adapter.state['layers']:row['name']='Same'
        self.window.refresh();before=self.window.layers.order()[:-1]
        self.drop(before[-1],QtCore.QPoint(15,0));self.item().setCheckState(2,QtCore.Qt.Unchecked)
        self.assertEqual(self.adapter.calls[-1][1]['layer'],before[-1])
    def test_get_and_initialize_buttons_are_removed(self):
        names=[button.text() for button in self.window.findChildren(QtWidgets.QPushButton)]
        self.assertNotIn('Get selected',names);self.assertNotIn('Initialize from current skin',names)
        self.assertIn('+',names);self.assertTrue(self.window.target.isReadOnly())
        self.assertNotIn('Show mask',[check.text() for check in self.window.findChildren(QtWidgets.QCheckBox)])
        self.assertNotIn('Fill mask',names);self.assertNotIn('Set layer mask',names)
        self.assertEqual(set(self.window.operation_groups),{'relax','replace','add','scale'})
        self.assertNotIn('Add chosen joints to layer',names);self.assertIn('Assign selected joints',names)
        self.assertIn('Rebuild layer',names);self.assertTrue(self.window.joint_dock.isAncestorOf(self.window.method))
    def test_assignment_method_enables_axis_controls_only_for_joint_axis(self):
        self.assertFalse(self.window.axis.isEnabled())
        for name in ('radius','falloff','length'):self.assertFalse(hasattr(self.window,name))
        self.window.method.setCurrentIndex(2)
        self.assertTrue(self.window.axis.isEnabled())
        self.window.method.setCurrentIndex(1)
        self.assertFalse(self.window.axis.isEnabled())
    def test_flood_then_assign_replaces_overrides_by_default_and_is_undoable(self):
        self.window.choose_joint('|a');self.window.whole.setChecked(True);self.assertTrue(self.window.run('flood'))
        before=self.adapter.snapshot();self.window.browser.paths=['|b'];self.window.browser_selected()
        self.window.method.setCurrentIndex(1)
        self.assertFalse(self.window.keep_paint.isChecked());self.assertTrue(self.window.assign())
        self.assertEqual(self.window.layer()['samples'],{})
        for actual,expected in zip(self.adapter.weights,[0,1,0,1,0,1]):self.assertAlmostEqual(actual,expected)
        self.assertTrue(self.adapter.calls[-1][1]['replace_manual']);self.window.history(False);self.assertEqual(self.adapter.snapshot(),before)
    def test_preserve_flood_option_and_rebuild_keep_overrides(self):
        self.window.choose_joint('|a');self.window.whole.setChecked(True);self.window.run('flood')
        original=copy.deepcopy(self.window.layer()['samples']);self.window.browser.paths=['|b'];self.window.browser_selected()
        self.window.keep_paint.setChecked(True);self.window.method.setCurrentIndex(1)
        self.assertTrue(self.window.assign());self.assertEqual(self.window.layer()['samples'],original)
        self.window.keep_paint.setChecked(False);self.assertTrue(self.window.assign(rebuild=True))
        self.assertEqual(self.window.layer()['samples'],original);self.assertFalse(self.adapter.calls[-1][1]['replace_manual'])
    def test_b_radius_sync_updates_field_without_reset_when_value_or_opacity_changes(self):
        self.window.paint();self.adapter.context_settings['radius']=3.75;before=self.adapter.snapshot()
        self.window.sync_brush_settings();self.assertEqual(self.window.brush_radius.value(),3.75)
        self.window.value.setValue(.4);self.window.value.editingFinished.emit()
        self.assertEqual(self.adapter.context_settings['radius'],3.75);self.assertEqual(self.adapter.context_settings['value'],.4)
        self.window.brush_opacity.setValue(.25);self.window.brush_opacity.editingFinished.emit()
        self.assertEqual(self.adapter.context_settings['radius'],3.75);self.assertEqual(self.adapter.snapshot(),before)
    def test_shift_brush_settings_use_separate_passes_shared_strength_and_joint_selection(self):
        self.window.brush_passes.setValue(2);self.window.relax_iterations.setValue(7);self.window.relax_strength.setValue(.3)
        self.window.relax_max_new.setValue(1);self.window.browser.paths=['|a','|b'];self.window._joint_source='browser'
        settings=self.window.brush_settings()
        self.assertEqual(settings,dict(iterations=2,strength=.3,max_new=1,preserve_coverage=False,joints=['a','b']))
    def test_selecting_an_unbound_joint_does_not_write_scene_data(self):
        before=self.adapter.snapshot();self.window.browser.paths=['|new'];self.window.browser_selected()
        self.assertEqual(self.adapter.snapshot(),before);self.assertEqual(self.adapter.calls,[])
        self.assertEqual(self.window.active_joint(),'new')
    def test_assignment_uses_live_hierarchy_selection_instead_of_a_hidden_cached_pick(self):
        self.window.browser.paths=['|b'];self.window.browser_selected()
        self.window.browser.paths=[]  # A scope rebuild removes the displayed pick without a selection signal.
        self.assertFalse(self.window.assign());self.assertEqual(self.adapter.calls,[])
        self.assertIn('Choose joints',self.window.status.text())
    def test_joint_switch_saves_old_pending_values_before_continuing_on_the_new_joint(self):
        self.window.paint();self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.8)
        self.window.browser.paths=['|new'];self.window.browser_selected()
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.session.joint,'new')
        self.assertIsNone(self.window.session.stroke);self.assertNotIn('new',self.adapter.ids);self.assertEqual(len(self.adapter.calls),1)
        self.window.choose_joint('|a');self.assertEqual(self.window.session.values,[.8,0.,0.])
        self.assertEqual(self.window.session.last_stroke['commit_reason'],'action_change')
    def test_release_fallback_waits_for_the_mouse_then_saves_missing_finalize_once(self):
        from unittest import mock
        self.window.choose_joint('|b');self.window.paint();session=self.window.session
        session.can_begin_stroke=lambda:True
        session.set_value(1,0,.8)  # No native initialize/before/finalize callbacks.
        with mock.patch.object(self.window,'brush_button_held',return_value=True):self.window.commit_released_stroke()
        self.assertEqual(self.adapter.calls,[]);self.assertTrue(self.window._paint_timer.isActive())
        with mock.patch.object(self.window,'brush_button_held',return_value=False):self.window.commit_released_stroke()
        session.finalize(1);self.window.commit_released_stroke();self.app.processEvents()
        self.assertEqual(session.values,[.8,0.,0.]);self.assertEqual(len(self.adapter.undo_stack),1)
        self.assertEqual(session.last_stroke['commit_reason'],'mouse_release_fallback')
        self.assertIn('Stroke saved',self.window.status.text())
    def test_qt_release_timer_saves_samples_without_native_begin_or_end_callbacks(self):
        self.window.choose_joint('|b');self.window.paint();session=self.window.session
        QtTest.QTest.mousePress(self.window,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,QtCore.QPoint(1,1))
        try:
            session.set_value(1,0,.8);QtTest.QTest.qWait(50)
            self.assertEqual(self.adapter.calls,[])
        finally:QtTest.QTest.mouseRelease(self.window,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,QtCore.QPoint(1,1))
        QtTest.QTest.qWait(80);self.app.processEvents()
        self.assertEqual(len(self.adapter.calls),1);self.assertEqual(session.values,[.8,0.,0.])
        self.window.choose_joint('|a');self.window.choose_joint('|b')
        self.assertEqual(session.values,[.8,0.,0.]);self.assertIn('0.80',self.window.display_range.text())
    def test_mask_repaint_saves_pending_paint_without_a_release_callback(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();session=self.window.session
        session.can_begin_stroke=lambda:True;session.set_value(1,0,.3)
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.assertEqual(session.values,[.3,1.,1.]);self.assertEqual(len(self.adapter.undo_stack),1)
        self.window.stop_paint();self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.assertEqual(session.values,[.3,1.,1.])
    def test_rejected_pending_save_stops_joint_switch_and_restores_selection(self):
        self.window.paint();session=self.window.session;session.before_stroke();session.set_value(1,0,.8)
        self.adapter.fail=True;self.window.browser.paths=['|b'];self.window.browser_selected()
        self.assertEqual(self.window.active_joint(),'a');self.assertEqual(session.joint,'a')
        self.assertEqual(self.window.browser.joints(),['|a']);self.assertTrue(session.active)
        self.assertIn('Stroke rejected',self.window.status.text());self.assertEqual(self.adapter.undo_stack,[])
    def test_reentrant_native_tool_change_cannot_restore_the_previous_joint_selection(self):
        self.window.paint();session=self.window.session;session.before_stroke();session.set_value(1,0,.8)
        activate=self.adapter.cmds.setToolTo
        def pump_events(name):
            activate(name);self.app.processEvents()
        self.adapter.cmds.setToolTo=pump_events
        self.window.browser.paths=['|b'];self.window.browser_selected();self.app.processEvents()
        self.assertEqual(self.window.browser.joints(),['|b']);self.assertEqual(self.window.active_joint(),'b')
        self.assertEqual(session.joint,'b');self.assertEqual(session.values,[0.]*3)
        self.window.browser.paths=['|a'];self.window.browser_selected();self.app.processEvents()
        self.assertEqual(self.window.browser.joints(),['|a']);self.assertEqual(session.values,[.8,0.,0.])
        self.assertEqual(len(self.adapter.undo_stack),1)
    def test_undo_cancels_pending_release_timer_without_reapplying_the_preview(self):
        self.window.run('properties',dict(name='An undoable edit'));self.window.paint();session=self.window.session
        session.before_stroke();session.set_value(1,0,.8);count=len(self.adapter.calls)
        self.adapter.undo()
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Undo':callback()
        QtTest.QTest.qWait(80);self.app.processEvents()
        self.assertEqual(len(self.adapter.calls),count);self.assertIsNone(session.stroke)
        self.assertEqual(self.adapter.weights,[1.,0.]*3)
    def test_scene_reset_cancels_release_timer_and_does_not_save_pending_samples(self):
        self.window.paint();session=self.window.session;session.before_stroke();session.set_value(1,0,.8)
        self.window.scene_reset();self.window.commit_released_stroke()
        self.assertFalse(self.window._paint_timer.isActive());self.assertEqual(self.adapter.calls,[])
    def test_maya_exit_cancels_late_release_work_without_scene_writes(self):
        self.window.paint();session=self.window.session;session.before_stroke();session.set_value(1,0,.8)
        session.maya_exit();self.window.commit_released_stroke()
        self.assertEqual(self.adapter.calls,[]);self.assertTrue(session.closed);self.assertIsNone(session.on_pending)
    def test_joint_selection_does_not_interrupt_mask_painting(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.2)
        stroke=copy.deepcopy(self.window.session.stroke);self.window.browser.paths=['|new'];self.window.browser_selected()
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.session.mode,'mask');self.assertEqual(self.window.session.stroke,stroke)
    def test_base_row_is_fixed_and_read_only(self):
        tree=self.window.layers;base=tree.topLevelItem(tree.topLevelItemCount()-1)
        self.assertEqual(tree.identity(base),ui.BASE);self.assertEqual(base.text(1),'Base · 0')
        self.assertFalse(base.flags() & QtCore.Qt.ItemIsDragEnabled)
        self.assertFalse(base.flags() & QtCore.Qt.ItemIsEditable)
        self.drop(ui.BASE,QtCore.QPoint(10,0));self.assertEqual(tree.order()[-1],ui.BASE)
        self.assertEqual([action.text() for action in tree.menu_for(base).actions()],['View mask'])
        self.assertEqual(self.adapter.calls,[])
    def test_selection_loads_without_creating_stack(self):
        self.adapter.attached=False;self.window.refresh();self.app.processEvents()
        self.assertEqual(self.window.layers.order(),[ui.BASE]);self.assertEqual(self.adapter.calls,[])
        self.assertFalse(self.adapter.attached)
    def test_first_plus_creates_stack_and_layer_in_one_undo(self):
        self.adapter.attached=False;self.window.refresh();self.window.run('add')
        self.assertTrue(self.adapter.attached);self.assertEqual(len(self.adapter.state['layers']),1)
        self.assertEqual(len(self.adapter.undo_stack),1);self.assertEqual(len(self.adapter.calls),1)
        self.window.history(False);self.assertFalse(self.adapter.attached);self.assertEqual(self.window.layers.order(),[ui.BASE])
    def test_joint_selection_keeps_mesh_without_bulk_reload(self):
        self.adapter.selected=['|b'];original=self.adapter.context;calls=[]
        self.adapter.context=lambda target:(calls.append(target),original(target))[1]
        self.window.follow_selection();self.assertEqual(self.window.target.text(),'meshShape');self.assertEqual(calls,[])
        self.assertEqual(self.window.active_joint(),'b')
    def test_pin_blocks_switching_to_another_selected_mesh(self):
        self.window.pin.setChecked(True);self.adapter.selected=['other']
        original_type=self.adapter.node_type;original_rel=self.adapter.relatives
        self.adapter.cmds.nodeType=lambda path:'transform' if path=='other' else 'mesh' if path=='otherShape' else original_type(path)
        self.adapter.cmds.listRelatives=lambda path,**kw:['otherShape'] if path=='other' else original_rel(path,**kw)
        self.window.follow_selection();self.assertEqual(self.window.target.text(),'meshShape')
    def test_window_hide_show_and_close_remove_listeners(self):
        self.assertEqual(len(self.adapter.callbacks),9)
        self.window.hide();self.app.processEvents();self.assertEqual(self.adapter.callbacks,{})
        self.window.show();self.app.processEvents();self.assertEqual(len(self.adapter.callbacks),9)
        browsers=list(self.adapter.browsers);self.window.close();self.app.processEvents()
        self.assertEqual(self.adapter.callbacks,{});self.assertTrue(all(browser.closed for browser in browsers))
    def test_qobject_destruction_without_close_removes_listeners_and_state(self):
        session=self.window.session;browsers=list(self.adapter.browsers)
        self.window.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertFalse(ui.shiboken.isValid(self.window));self.assertTrue(session.closed)
        self.assertEqual(self.adapter.callbacks,{});self.assertTrue(all(browser.closed for browser in browsers))
        self.assertIsNone(self.window.ctx);self.assertIsNone(self.window.state);self.assertEqual(self.window.rows,[])
    def test_layer_selection_saves_pending_mask_to_the_previous_layer(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.session.initialize('meshShape');previous=self.window.selected_id()
        self.window.session.set_value(1,0,.2);self.window.layers.setCurrentItem(self.item(1),1)
        self.assertFalse(self.window.session.active);self.assertIsNone(self.window.session.stroke);self.assertEqual(len(self.adapter.calls),1)
        self.assertEqual(next(row for row in self.adapter.state['layers'] if row['id']==previous)['mask'],{'0':.2})
    def test_paint_mask_shows_values_and_stop_restores_tool(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.assertFalse(self.window.session.readonly);self.assertTrue(self.window.session.active)
        self.window.stop_paint();self.assertFalse(self.window.session.active);self.assertEqual(self.adapter.tool,'selectSuperContext')
        self.assertEqual(self.adapter.calls,[])
    def test_painted_mask_survives_stop_and_repaint_and_joint_actions(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();session=self.window.session
        session.before_stroke();session.set_value(1,0,.25);session.set_value(1,1,.6);session.after_stroke();self.app.processEvents()
        expected=[.25,.6,1.];saved=self.adapter.snapshot();calls=len(self.adapter.calls)
        self.assertEqual(session.values,expected);self.assertIn('0.25',self.window.display_range.text())
        for repeat in range(3):
            self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.assertEqual(session.values,expected)
            self.window.stop_paint();self.window.choose_joint('|b');self.window.paint_mode.setCurrentIndex(1);self.window.paint()
            self.assertEqual(session.values,expected);self.assertIn('0.25',self.window.display_range.text())
            self.window.paint();self.window.choose_joint('|a');self.assertEqual(session.values,expected)
        self.assertEqual(self.adapter.snapshot(),saved);self.assertEqual(len(self.adapter.calls),calls)
    def test_painted_joint_weights_return_after_joint_mask_and_final_view_switches(self):
        self.window.choose_joint('|b');self.window.paint();session=self.window.session
        session.before_stroke();session.set_value(1,0,.8);session.set_value(1,1,.4);session.after_stroke();self.app.processEvents()
        saved=self.adapter.snapshot();calls=len(self.adapter.calls);layer=self.window.selected_id()
        for repeat in range(3):
            self.window.choose_joint('|a');self.assertEqual(session.values,[0.]*3)
            self.window.choose_joint('|b');self.assertEqual(session.values,[.8,.4,0.])
            self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.show_skin.setChecked(True);self.window.paint_mode.setCurrentIndex(0);self.window.paint()
            self.assertEqual(session.values,[.8,.4,0.]);self.assertIn('0.80',self.window.display_range.text())
        self.assertEqual(self.window.selected_id(),layer);self.assertEqual(self.adapter.snapshot(),saved);self.assertEqual(len(self.adapter.calls),calls)
    def test_reopened_window_loads_serialized_weights_and_mask_instead_of_old_session_buffers(self):
        self.window.choose_joint('|b');self.window.paint();session=self.window.session
        session.before_stroke();session.set_value(1,0,.8);session.after_stroke()
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        session.before_stroke();session.set_value(1,1,.3);session.after_stroke();self.app.processEvents()
        saved=self.adapter.snapshot();self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.adapter.state=core.decode(core.encode(self.adapter.state))
        self.window=ui.LayerUI(self.adapter);self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
        self.window.choose_joint('|b');self.window.paint();self.assertEqual(self.window.session.values,[.8,0.,0.])
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.assertEqual(self.window.session.values,[1.,.3,1.])
        self.assertEqual(self.adapter.snapshot(),saved)
    def test_show_final_skin_weights_displays_the_actual_skin_without_writing(self):
        self.adapter.weights=[.25,.75]*3;self.window.choose_joint('|b');before=self.adapter.snapshot()
        self.window.show_skin.setChecked(True)
        self.assertTrue(self.window.session.active);self.assertTrue(self.window.session.readonly)
        self.assertEqual(self.window.session.mode,'skin');self.assertEqual(self.window.session.values,[.75]*3)
        self.assertIn('Final skin weights',self.window.status.text());self.assertEqual(self.adapter.snapshot(),before)
        self.assertEqual(self.adapter.calls,[])
    def test_final_skin_view_and_mask_paint_are_mutually_exclusive(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.show_skin.setChecked(True)
        self.assertTrue(self.window.session.active);self.assertTrue(self.window.show_skin.isChecked());self.assertEqual(self.window.session.mode,'skin')
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.assertFalse(self.window.show_skin.isChecked());self.assertEqual(self.window.session.mode,'mask');self.assertFalse(self.window.session.readonly)
    def test_switching_joint_updates_final_skin_view_without_leaving_readonly_mode(self):
        self.adapter.weights=[.25,.75]*3;self.window.choose_joint('|a');self.window.show_skin.setChecked(True)
        self.assertEqual(self.window.session.values,[.25]*3)
        self.window.browser.paths=['|b'];self.window.browser_selected()
        self.assertTrue(self.window.show_skin.isChecked());self.assertTrue(self.window.session.active);self.assertTrue(self.window.session.readonly)
        self.assertEqual(self.window.session.values,[.75]*3);self.assertEqual(self.adapter.calls,[])
    def test_paint_leaves_final_skin_view_and_edits_the_selected_layer(self):
        self.window.choose_joint('|b');self.window.show_skin.setChecked(True);self.window.paint()
        self.assertFalse(self.window.show_skin.isChecked());self.assertFalse(self.window.session.readonly)
        self.assertEqual(self.window.session.mode,'weights');self.assertEqual(self.window.session.values,[0.]*3)
        self.assertIn('Replace brush',self.window.status.text())
    def test_native_tool_handoff_saves_before_switch_and_late_timer_does_not_write(self):
        self.window.choose_joint('|b');self.window.paint();session=self.window.session
        session.before_stroke();self.adapter.paint_buffer.write([.7,0.,0.])
        session.tool_cleanup();self.adapter.tool='artAttrSkinContext';self.adapter.fail=True
        self.app.processEvents();QtTest.QTest.qWait(70);self.app.processEvents()
        self.window.commit_released_stroke()
        self.assertEqual(len(self.adapter.calls),1);self.assertEqual(len(self.adapter.undo_stack),1)
        self.assertIsNone(self.adapter._chunk);self.assertFalse(self.window._paint_timer.isActive())
        self.assertFalse(session.active);self.assertEqual(self.adapter.tool,'artAttrSkinContext')
        self.assertEqual(self.adapter.warnings,[])
    def test_native_tool_keeps_control_when_a_joint_is_chosen_in_layer_hierarchy(self):
        self.window.paint();self.adapter.tool='artAttrSkinContext'
        # Guard the actual context even if Maya did not deliver cleanup yet.
        self.window.choose_joint('|b')
        self.assertEqual(self.adapter.tool,'artAttrSkinContext');self.assertFalse(self.window.session.active)
        self.assertEqual(self.window.active_joint(),'b');self.assertEqual(self.adapter.calls,[])
    def test_native_strokes_keep_layer_metadata_and_explain_how_to_resume(self):
        saved=copy.deepcopy(self.adapter.state);self.adapter.tool='artAttrSkinContext';self.adapter.weights[:2]=[.5,.5]
        self.window.paint()
        self.assertFalse(self.window.session.active);self.assertEqual(self.adapter.tool,'artAttrSkinContext')
        self.assertEqual(self.adapter.state,saved);self.assertEqual(self.adapter.calls,[])
        self.assertIn('Undo the native strokes',self.window.status.text())
        self.adapter.weights=core.composite(self.adapter.state);self.window.paint()
        self.assertTrue(self.window.session.active)
    def test_final_skin_view_works_before_any_editable_layer_is_added(self):
        self.adapter.attached=False;self.window.refresh();self.window.choose_joint('|a')
        self.window.show_skin.setChecked(True)
        self.assertEqual(self.window.session.values,[1.]*3);self.assertTrue(self.window.session.readonly)
        self.assertFalse(self.adapter.attached);self.assertEqual(self.adapter.calls,[])
    def test_axis_assignment_ui_passes_explicit_scope_and_parameters(self):
        calls=[];self.adapter.cmds.rtkLayerSkin=lambda **kw:calls.append(kw)
        self.window.method.setCurrentIndex(2);self.window.axis.setCurrentText('-X')
        self.window.assignment_scope.setCurrentIndex(1);self.window.assign()
        data=json.loads(calls[0]['data']);self.assertEqual(calls[0]['action'],'assign')
        self.assertEqual(data['settings']['axis'],'-X');self.assertFalse(data['whole'])
        self.assertNotIn('radius',data['settings']);self.assertNotIn('length',data['settings']);self.assertNotIn('falloff',data['settings'])
    def test_axis_rebuild_uses_all_layer_joints_without_replacing_paint_or_masks(self):
        layer=self.window.selected_id()
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.6}))
        self.window.run('paint',dict(mode='mask',values={'1':.25}))
        before=copy.deepcopy(self.window.layer())
        self.window.method.setCurrentIndex(2);self.window.browser.paths=['|a'];self.window.browser_selected()
        self.assertTrue(self.window.assign(rebuild=True))
        row=self.window.layer();self.assertEqual(row['samples'],before['samples']);self.assertEqual(row['mask'],before['mask'])
        self.assertEqual(self.adapter.calls[-1][1]['joints'],['a','b'])
    def test_heatmap_default_and_grayscale_switch_do_not_change_authoring_data(self):
        before=self.adapter.snapshot();self.window.paint()
        self.assertEqual(self.window.weight_display.currentText(),'Heat map');self.assertTrue(self.adapter.context_settings['useColorRamp'])
        self.window.weight_display.setCurrentIndex(1);self.assertFalse(self.adapter.context_settings['useColorRamp'])
        self.assertEqual(self.adapter.snapshot(),before);self.assertEqual(self.adapter.calls,[])
        self.window.paint_mode.setCurrentIndex(1);self.window.weight_display.setCurrentIndex(0);self.window.paint()
        self.assertFalse(self.adapter.context_settings['useColorRamp']);self.assertIn('stop:0 black',self.window.ramp_preview.styleSheet())
    def pause_view(self,components):
        self.window.paint();self.adapter.tool='selectSuperContext';self.window.session.tool_cleanup()
        self.adapter.selected=components;self.adapter.object_mode=False
    def test_vertex_and_edge_selection_keep_heatmap_without_refresh_or_tool_changes(self):
        self.pause_view(['mesh.vtx[0]']);self.window.session.needs_refresh=False
        with mock.patch.object(self.window.session,'snapshot',side_effect=AssertionError('Unexpected skin read')):
            self.window.follow_selection();self.adapter.selected=['mesh.e[0]'];self.window.follow_selection()
        self.assertTrue(self.adapter.weight_view.visible);self.assertEqual(self.adapter.tool,'selectSuperContext')
        self.assertEqual(self.adapter.selected,['mesh.e[0]']);self.assertFalse(self.adapter.object_mode)
    def test_relax_keeps_component_selection_and_refreshes_paused_heatmap(self):
        self.window.run('paint',dict(mode='weights',joint='a',values={'0':1.}))
        self.window.run('paint',dict(mode='weights',joint='b',values={'1':1.,'2':1.}))
        self.pause_view(['mesh.vtx[0]']);self.assertTrue(self.window.relax())
        self.assertTrue(self.adapter.weight_view.visible);self.assertEqual(self.adapter.selected,['mesh.vtx[0]'])
        self.assertEqual(self.adapter.tool,'selectSuperContext');self.assertFalse(self.adapter.object_mode)
        self.assertEqual(self.adapter.weight_view.values,self.window.session.values)
    def test_relax_while_brushing_restores_the_brush_and_array(self):
        self.window.paint();self.assertTrue(self.window.relax())
        self.assertTrue(self.window.session.active);self.assertEqual(self.adapter.tool,self.adapter.paint_context)
        self.assertIs(self.adapter.paint_buffer.owner,self.window.session)
    def test_joint_layer_mask_switch_while_paused_updates_colors_without_selecting_tool(self):
        self.pause_view(['mesh.e[0]']);self.window.choose_joint('|b')
        self.assertEqual(self.window.session.joint,'b');self.assertTrue(self.adapter.weight_view.visible)
        self.window.layers.setCurrentItem(self.item(1),1)
        self.assertEqual(self.window.session.layer,self.window.selected_id())
        self.window.paint_mode.setCurrentIndex(1)
        self.assertEqual(self.adapter.weight_view.display,'grayscale');self.assertEqual(self.adapter.weight_view.values,[1.,1.,1.])
        self.assertEqual(self.adapter.selected,['mesh.e[0]']);self.assertEqual(self.adapter.tool,'selectSuperContext')
    def test_stop_shaded_view_is_explicit_and_undo_keeps_viewing(self):
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.8}))
        self.pause_view(['mesh.vtx[0]']);self.window.history(False)
        self.assertTrue(self.window.session.viewing);self.assertTrue(self.adapter.weight_view.visible)
        self.window.stop_paint();self.assertFalse(self.window.session.viewing);self.assertFalse(self.adapter.weight_view.visible)
    def test_failed_relax_retains_color_view_and_component_selection(self):
        self.pause_view(['mesh.vtx[0]']);before=self.adapter.snapshot();self.adapter.fail=True
        self.assertFalse(self.window.relax());self.assertTrue(self.adapter.weight_view.visible)
        self.assertEqual(self.adapter.snapshot(),before);self.assertEqual(self.adapter.selected,['mesh.vtx[0]'])
        self.assertEqual(self.adapter.tool,'selectSuperContext')
    def test_add_and_delete_layer_retarget_the_paused_view(self):
        self.pause_view(['mesh.e[0]']);self.window.run('add')
        self.assertTrue(self.adapter.weight_view.visible);self.assertEqual(self.window.session.layer,self.window.selected_id())
        self.window.run('delete');self.assertTrue(self.adapter.weight_view.visible)
        self.assertEqual(self.window.session.layer,self.window.selected_id());self.assertEqual(self.adapter.selected,['mesh.e[0]'])
    def test_flood_relax_selected_vertices_is_one_edit_with_options_and_undo(self):
        self.window.run('paint',dict(mode='weights',joint='a',values={'0':1.}))
        self.window.run('paint',dict(mode='weights',joint='b',values={'1':1.,'2':1.}))
        self.adapter.selected=['mesh.vtx[0]'];before=self.adapter.snapshot();count=len(self.adapter.undo_stack)
        self.window.relax_iterations.setValue(2);self.window.relax_strength.setValue(.5);self.window.relax_max_new.setValue(1)
        self.window.browser.paths=['|a'];self.window._joint_source='browser';self.assertTrue(self.window.relax())
        action,data=self.adapter.calls[-1];self.assertEqual(action,'relax')
        self.assertEqual((data['iterations'],data['strength'],data['max_new']),(2,.5,1));self.assertEqual(data['joints'],['a'])
        self.assertEqual(len(self.adapter.undo_stack),count+1);self.assertEqual(self.adapter.weights,[.25,.75,0.,1.,0.,1.])
        self.window.history(False);self.assertEqual(self.adapter.snapshot(),before)
    def test_flood_relax_without_vertices_uses_entire_mesh_and_passes_joint_subset(self):
        self.window.run('paint',dict(mode='weights',joint='a',values={'0':1.}))
        self.window.run('paint',dict(mode='weights',joint='b',values={'1':1.,'2':1.}))
        self.adapter.selected=['mesh'];self.window.browser.paths=['|a','|b'];self.window._joint_source='browser'
        self.window.relax_iterations.setValue(1);self.assertTrue(self.window.relax())
        self.assertEqual(self.adapter.calls[-1][1]['joints'],['a','b']);self.assertEqual(self.adapter.weights,[.5,.5,.25,.75,0.,1.])
    def test_relax_on_base_is_rejected_without_a_command(self):
        self.window.layers.setCurrentItem(self.item(self.window.layers.topLevelItemCount()-1),1)
        self.assertFalse(self.window.relax());self.assertEqual(self.adapter.calls,[])
    def test_native_browser_selection_uses_layer_joint_uuid(self):
        self.window.browser.paths=['|b'];self.window.browser_selected();self.assertEqual(self.window.active_joint(),'b')
    def test_marked_scope_controls_are_removed_and_all_skin_roots_are_loaded(self):
        self.assertFalse(hasattr(self.window,'root'));self.assertFalse(hasattr(self.window,'scope_selected'))
        self.assertNotIn('Scope to selected joint',[button.text() for button in self.window.joint_dock.findChildren(QtWidgets.QPushButton)])
        self.adapter.selected=['|b'];self.window.follow_selection()
        self.assertEqual(self.window.browser.roots[-1],('|a','|b'))
    def test_native_browser_guard_blocks_scene_edit_gestures(self):
        from layer_skin_session import protect_browser_widget
        tree=QtWidgets.QTreeWidget();item=QtWidgets.QTreeWidgetItem(tree,['Joint'])
        item.setFlags(item.flags()|QtCore.Qt.ItemIsEditable);tree.setDragEnabled(True);tree.setAcceptDrops(True)
        guard=protect_browser_widget(tree)
        self.assertFalse(tree.dragEnabled());self.assertFalse(tree.acceptDrops())
        self.assertEqual(tree.editTriggers(),QtWidgets.QAbstractItemView.NoEditTriggers)
        for key in (QtCore.Qt.Key_Delete,QtCore.Qt.Key_Backspace,QtCore.Qt.Key_F2):
            event=ui.QtGui.QKeyEvent(QtCore.QEvent.KeyPress,key,QtCore.Qt.NoModifier)
            self.assertTrue(guard.eventFilter(tree,event))
        tree.deleteLater()
    def test_new_viewport_joint_pick_takes_priority_over_old_browser_pick(self):
        self.window.browser.paths=['|a'];self.window.browser_selected()
        self.adapter.selected=['|new'];self.window.follow_selection();self.window.assign()
        self.assertEqual(next(event for event in self.adapter.events if event[0]=='add_influence')[1]['addInfluence'],'|new')
    def test_new_browser_pick_takes_priority_over_unchanged_viewport_selection(self):
        self.adapter.selected=['|a'];self.window.follow_selection()
        self.window.browser.paths=['|new'];self.window.browser_selected();self.window.assign()
        self.assertEqual(next(event for event in self.adapter.events if event[0]=='add_influence')[1]['addInfluence'],'|new')
    def test_scene_reset_stops_session_and_clears_stale_data(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.scene_reset()
        self.assertFalse(self.window.session.active);self.assertEqual(self.window.target.text(),'');self.assertEqual(self.window.layers.order(),[])
    def test_history_callback_refreshes_without_selection_change(self):
        self.adapter.state['layers'][-1]['name']='External Undo result'
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Undo':callback()
        self.app.processEvents();self.assertEqual(self.item().text(1),'External Undo result')
    def test_history_refreshes_active_mask_view_scalar_buffer(self):
        layer=self.window.selected_id()
        self.adapter.command(action='paint',data=json.dumps(dict(layer=layer,mode='mask',values={'0':.25})))
        self.window.refresh(layer);self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.assertEqual(self.window.session.get_value(1,0),.25)
        self.adapter.undo()
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Undo':callback()
        self.app.processEvents()
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.session.mode,'mask')
        self.assertEqual(self.window.session.get_value(1,0),1.)
        self.adapter.redo()
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Redo':callback()
        self.app.processEvents();self.assertEqual(self.window.session.get_value(1,0),.25)
    def test_undo_discards_unfinished_stroke_before_refreshing_brush(self):
        layer=self.window.selected_id()
        self.adapter.command(action='properties',data=json.dumps(dict(layer=layer,name='Before undo')))
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.2)
        calls=len(self.adapter.calls);self.adapter.undo()
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Undo':callback()
        self.app.processEvents()
        self.assertIsNone(self.window.session.stroke);self.assertEqual(self.window.session.get_value(1,0),1.)
        self.window.session.finalize(1);self.assertEqual(len(self.adapter.calls),calls)
    def test_undo_removing_painted_layer_restores_previous_tool(self):
        self.window.run('add');self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        self.adapter.undo()
        for kind,callback in self.adapter.callbacks.values():
            if kind=='Undo':callback()
        self.app.processEvents()
        self.assertFalse(self.window.session.active);self.assertEqual(self.adapter.tool,'selectSuperContext')
    def test_hierarchy_is_the_only_joint_selector_and_is_docked_right(self):
        self.assertEqual(self.window.findChildren(QtWidgets.QListWidget),[])
        self.assertEqual(self.window.dock_layout.dockWidgetArea(self.window.joint_dock),QtCore.Qt.RightDockWidgetArea)
        self.assertTrue(self.window.joint_dock.isAncestorOf(self.window.browser_host))
        self.assertGreater(self.window.joint_dock.x(),self.window.dock_layout.centralWidget().x())
        self.assertGreater(self.window.browser_host.height(),230)
    def test_empty_layer_members_are_gray_but_selectable_for_paint(self):
        self.assertEqual(self.window.browser.weighted,set());self.assertEqual(self.window.browser.members,{'a','b'})
        self.window.browser.paths=['|b'];self.window.browser_selected();self.window.paint()
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.session.joint,'b')
        self.assertIn('b',self.window.paint_joint.text())
    def test_paint_stroke_updates_the_single_hierarchy_weight_status(self):
        self.window.browser.paths=['|b'];self.window.browser_selected();self.window.paint()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.6);self.window.session.finalize(1)
        self.app.processEvents();self.assertEqual(self.window.browser.weighted,{'b'})
        self.assertEqual(len(self.adapter.calls),1)
    def test_changing_layer_updates_weight_status_and_preserves_joint(self):
        top=self.window.selected_id();lower=self.adapter.state['layers'][-2]['id']
        self.adapter.state=core.edit(self.adapter.state,'paint',dict(layer=top,mode='weights',joint='b',values={'0':1.}))
        self.adapter.state=core.edit(self.adapter.state,'paint',dict(layer=lower,mode='weights',joint='a',values={'0':1.}))
        self.window.refresh(top);self.window.browser.paths=['|b'];self.window.browser_selected()
        self.assertEqual(self.window.browser.weighted,{'b'})
        self.window.layers.setCurrentItem(self.item(1),1)
        self.assertEqual(self.window.browser.weighted,{'a'});self.assertEqual(self.window.active_joint(),'b')
        self.assertEqual(self.adapter.calls,[])
    def test_base_status_uses_captured_weights_instead_of_membership(self):
        self.window.layers.setCurrentItem(self.item(self.window.layers.topLevelItemCount()-1),1)
        self.assertEqual(self.window.browser.members,{'a','b'});self.assertEqual(self.window.browser.weighted,{'a'})
    def test_browser_joint_change_keeps_the_brush_active_on_the_new_joint(self):
        self.window.paint();self.assertTrue(self.window.session.active)
        self.window.browser.paths=['|b'];self.window.browser_selected()
        self.assertTrue(self.window.session.active);self.assertEqual(self.window.active_joint(),'b')
        self.assertEqual(self.window.session.joint,'b');self.assertEqual(self.adapter.calls,[])
    def test_unbound_joint_is_painted_directly_from_the_same_hierarchy(self):
        self.window.browser.paths=['|new'];self.window.browser_selected()
        self.assertEqual(self.window.active_joint(),'new');self.assertNotIn('new',self.window.browser.members)
        self.assertNotIn('new',self.window.browser.weighted)
        self.window.paint();self.assertTrue(self.window.session.active)
        self.assertNotIn('new',self.adapter.ids)
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.8);self.window.session.finalize(1)
        self.app.processEvents()
        self.assertIn('new',self.window.browser.members);self.assertIn('new',self.window.browser.weighted)
        self.assertEqual(len(self.adapter.undo_stack),1)
    def test_joint_dock_can_float_and_return_without_an_extra_browser(self):
        browser=self.window.browser
        self.window.joint_dock.setFloating(True);self.app.processEvents()
        self.assertTrue(self.window.joint_dock.isFloating())
        self.window.joint_dock.setFloating(False);self.app.processEvents()
        self.assertFalse(self.window.joint_dock.isFloating());self.assertIs(self.window.browser,browser)
        self.assertEqual(len(self.adapter.browsers),1)
    def test_gray_status_summary_is_reused_for_alpha_edits(self):
        from unittest import mock
        with mock.patch.object(core,'weighted_influences',wraps=core.weighted_influences) as summary:
            self.window.run('properties',dict(opacity=.5))
            summary.assert_not_called()
        self.assertEqual(self.window.browser.weighted,set())

    def test_revisiting_layers_and_base_reuses_unchanged_weight_summaries(self):
        tree=self.window.layers;selected=self.window.selected_id()
        with mock.patch.object(core,'weighted_influences',wraps=core.weighted_influences) as summary:
            for _ in range(3):
                for i in range(tree.topLevelItemCount()):tree.setCurrentItem(self.item(i),1)
            # The initially selected layer was summarized during window setup.
            self.assertEqual(summary.call_count,tree.topLevelItemCount()-1)
        self.assertEqual(self.adapter.calls,[])
        tree.setCurrentItem(self.item(),1);self.assertEqual(self.window.selected_id(),selected)

    def test_paint_and_history_invalidate_only_current_saved_weight_sources(self):
        tree=self.window.layers;top=self.window.selected_id();lower=self.window.rows[1]['id']
        tree.setCurrentItem(self.item(1),1);tree.setCurrentItem(self.item(),1)
        self.window.paint();self.window.session.initialize('meshShape')
        self.window.session.set_value(1,0,.8);self.window.session.finalize(1);self.app.processEvents()
        self.assertEqual(self.window.browser.weighted,{'a'})
        self.window.history(False);self.assertEqual(self.window.browser.weighted,set())
        self.window.history(True);self.assertEqual(self.window.browser.weighted,{'a'})
        tree.setCurrentItem(self.item(1),1)
        self.assertEqual(self.window.selected_id(),lower);self.assertEqual(self.window.browser.weighted,set())
        tree.setCurrentItem(self.item(),1)
        self.assertEqual(self.window.selected_id(),top);self.assertEqual(self.window.browser.weighted,{'a'})

    def test_clear_memory_caches_also_releases_layer_summaries(self):
        self.window.layers.setCurrentItem(self.item(1),1)
        self.assertIsNotNone(self.window._weight_status)
        self.assertTrue(self.window.clear_cache());self.assertIsNone(self.window._weight_status)
        with mock.patch.object(core,'weighted_influences',wraps=core.weighted_influences) as summary:
            self.window.populate_joints();summary.assert_called_once()


    def test_ui_session_refresh_saves_pending_mask_keeps_scope_and_updates_session_factory(self):
        import layer_skin_ui_refresh as refresh_ui
        self.window.choose_joint('|b');self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        old_session=self.window.session;old_session.before_stroke();old_session.set_value(1,0,.2)
        layer=self.window.selected_id();target=self.window.target.text();callbacks=len(self.adapter.callbacks)
        self.window.pin.setChecked(True);self.window.whole.setChecked(True)
        self.window.value.setValue(.4);self.window.brush_radius.setValue(2);self.window.brush_opacity.setValue(.5)
        for control in (self.window.value,self.window.brush_radius,self.window.brush_opacity):control.editingFinished.emit()
        self.window.brush_passes.setValue(2);self.window.preserve_coverage.setChecked(False);self.window.keep_paint.setChecked(True)
        self.window.relax_iterations.setValue(7);self.window.relax_strength.setValue(.3);self.window.relax_max_new.setValue(2)
        self.window.weight_display.setCurrentIndex(1)
        old_assignment=types.SimpleNamespace(CACHE=object())
        owner={'VERSION':self.adapter.VERSION,'WINDOW':self.adapter.WINDOW,'_ui_module':object(),'_modules':{'unrelated':object(),'layer_skin_assignment':old_assignment},'old_factory':self.adapter.make_session}
        unrelated=owner['_modules']['unrelated']
        exec('def make_session():\n    return old_factory()\n',owner)
        self.adapter.make_session=owner['make_session']
        self.window=refresh_ui.refresh(self.window);self.app.processEvents()
        self.assertTrue(old_session.closed);self.assertFalse(self.window.session.active)
        self.assertEqual(self.window.target.text(),target);self.assertEqual(self.window.selected_id(),layer)
        self.assertEqual(self.window.active_joint(),'b');self.assertEqual(self.window.paint_mode.currentIndex(),1)
        self.assertTrue(self.window.pin.isChecked());self.assertTrue(self.window.whole.isChecked())
        self.assertEqual((self.window.value.value(),self.window.brush_radius.value(),self.window.brush_opacity.value()),(.4,2.,.5))
        self.assertEqual((self.window.relax_iterations.value(),self.window.relax_strength.value(),self.window.relax_max_new.value()),(7,.3,2))
        self.assertEqual(self.window.brush_passes.value(),2);self.assertFalse(self.window.preserve_coverage.isChecked());self.assertTrue(self.window.keep_paint.isChecked())
        self.assertEqual(self.window.weight_display.currentText(),'Grayscale')
        self.assertFalse(hasattr(self.window,'show_mask'));self.assertIn('UI 38',self.window.windowTitle())
        self.assertIs(owner['_ui_module']._dialog,self.window);self.assertEqual(len(self.adapter.callbacks),callbacks)
        self.assertEqual(len(self.adapter.undo_stack),1)
        self.window.paint();self.assertEqual(self.window.session.values,[.2,1.,1.])
        self.assertEqual(type(self.window.session).__module__,'_rtk_layer_skin_session_memory_20')
        stale_brush=types.SimpleNamespace(stale=True)
        with mock.patch.dict(__import__('sys').modules,{'_rtk_layer_skin_authoring_18_layer_skin_brush_view':stale_brush}):
            current_brush=self.window.session.helper('layer_skin_brush_view')
            self.assertIsNot(current_brush,stale_brush)
            self.assertIs(current_brush,__import__('sys').modules['_rtk_layer_skin_authoring_37_layer_skin_brush_view'])
        self.assertIs(self.window.session.api.make_paint_buffer,self.adapter.make_paint_buffer)
        self.assertIs(owner['_modules']['layer_skin_session'].Session,type(self.window.session))
        self.assertIs(owner['_modules']['unrelated'],unrelated)
        self.assertIs(owner['_modules']['layer_skin_assignment'],__import__('sys').modules['_rtk_layer_skin_assignment_041'])
        self.assertEqual(owner['_modules']['layer_skin_assignment'].CACHE.stats()['builds'],0)
        self.assertIs(old_assignment.CACHE,owner['_modules']['layer_skin_assignment'].CACHE)
        self.window.session.before_stroke();self.adapter.paint_buffer.write([.4,1.,1.]);self.window.session.tool_cleanup()
        self.assertEqual(self.adapter.state['layers'][-1]['mask'],{'0':.4})
        self.assertEqual(len(self.adapter.undo_stack),2)
        self.window=refresh_ui.refresh(self.window);self.app.processEvents();self.window.paint()
        self.assertEqual(self.window.session.values,[.4,1.,1.]);self.assertIs(owner['_ui_module']._dialog,self.window)

    def test_ui_refresh_keeps_window_and_data_when_pending_stroke_is_rejected(self):
        import layer_skin_ui_refresh as refresh_ui
        self.window.paint_mode.setCurrentIndex(1);self.window.paint()
        session=self.window.session;session.before_stroke();session.set_value(1,0,.2)
        saved=self.adapter.snapshot();self.adapter.fail=True
        with self.assertRaisesRegex(RuntimeError,'pending paint stroke could not be saved'):
            refresh_ui.refresh(self.window)
        self.assertFalse(self.window._closed);self.assertTrue(session.active)
        self.assertTrue(self.window.isVisible());self.assertEqual(self.adapter.snapshot(),saved)

    def test_shift_coverage_default_and_one_time_migration_allow_visible_boundary_smoothing(self):
        import layer_skin_ui_refresh as refresh_ui
        self.assertFalse(self.window.preserve_coverage.isChecked())
        self.assertFalse(self.window.brush_settings()['preserve_coverage'])
        before=self.adapter.snapshot()
        self.window.relax_brush_revision=10;self.window.preserve_coverage.setChecked(True)
        self.window=refresh_ui.refresh(self.window);self.app.processEvents()
        self.assertFalse(self.window.preserve_coverage.isChecked());self.assertEqual(self.adapter.snapshot(),before)
        self.window.preserve_coverage.setChecked(True)
        self.window=refresh_ui.refresh(self.window);self.app.processEvents()
        self.assertTrue(self.window.preserve_coverage.isChecked());self.assertEqual(self.adapter.snapshot(),before)

    def test_ui_refresh_removes_legacy_overlay_ignores_old_brush_cache_and_redraws(self):
        import layer_skin_ui_refresh as refresh_ui
        from unittest import mock
        import sys
        del self.adapter.make_brush_controller
        self.window.choose_joint('|b');self.window.paint();before=self.adapter.snapshot();self.window.session.brush.close()
        viewport=QtWidgets.QWidget();viewport.show();overlay=QtWidgets.QWidget(viewport);overlay.show()
        closed=[]
        class LegacyBrush:
            drawing=False
            def close(self):closed.append(True);overlay.hide();overlay.deleteLater()
        self.window.session.brush=LegacyBrush()
        old_helper=types.SimpleNamespace(attach=mock.Mock(side_effect=AssertionError('old brush reused')))
        self.adapter.cmds.refresh=mock.Mock()
        try:
            with mock.patch.dict(sys.modules,{'_rtk_layer_skin_authoring_9_layer_skin_brush_view':old_helper}):
                self.window=refresh_ui.refresh(self.window);self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
                self.assertEqual(closed,[True]);self.assertEqual(viewport.findChildren(QtWidgets.QWidget),[])
                self.adapter.cmds.refresh.assert_called_once_with(force=True)
                self.assertEqual(self.adapter.snapshot(),before)
                self.window.paint();brush=self.window.session.brush
                self.assertEqual(brush.report()['feedback_backend'],'Maya Artisan outline')
                self.assertFalse(brush.report()['qt_viewport_overlay']);old_helper.attach.assert_not_called()
                self.assertEqual(self.window.session.paint_report()['authoring_revision'],'ui35_viewport_constructor')
        finally:viewport.close();viewport.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)


@unittest.skipIf(ui is None,'PySide is required for joint styling checks')
class JointStylingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        from layer_skin_joint_view import JointStyling
        self.tree=QtWidgets.QTreeWidget();self.tree.setHeaderHidden(True)
        a=QtWidgets.QTreeWidgetItem(self.tree,['left']);b=QtWidgets.QTreeWidgetItem(self.tree,['right'])
        self.a=QtWidgets.QTreeWidgetItem(a,['joint']);self.b=QtWidgets.QTreeWidgetItem(b,['joint'])
        self.tree.expandAll();self.styling=JointStyling(self.tree)
        self.styling.update({'|rig|left|joint':'a','|rig|right|joint':'b'},{'b'},{'a','b'})
        self.delegate=self.styling.delegates[0]
    def tearDown(self):self.tree.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_duplicate_joint_names_resolve_by_their_displayed_parents(self):
        self.assertTrue(self.delegate.is_empty(self.tree.indexFromItem(self.a)))
        self.assertFalse(self.delegate.is_empty(self.tree.indexFromItem(self.b)))
    def test_empty_joint_uses_gray_text_without_disabling_or_modifying_the_model(self):
        red=ui.QtGui.QColor(255,0,0);self.a.setForeground(0,red)
        option=self.delegate.empty_option(QtWidgets.QStyleOptionViewItem(),self.tree.indexFromItem(self.a))
        color=option.palette.color(ui.QtGui.QPalette.Text)
        self.assertEqual(color.red(),color.green());self.assertEqual(color.green(),color.blue())
        self.assertNotEqual(color,red);self.assertEqual(self.a.foreground(0).color(),red)
        self.assertTrue(self.a.flags() & QtCore.Qt.ItemIsEnabled);self.assertTrue(self.a.flags() & QtCore.Qt.ItemIsSelectable)
    def test_weighted_rows_keep_the_original_native_delegate(self):
        from unittest import mock
        original=self.delegate.original;self.delegate.original=mock.Mock()
        self.delegate.paint(None,QtWidgets.QStyleOptionViewItem(),self.tree.indexFromItem(self.b))
        self.delegate.original.paint.assert_called_once();self.delegate.original=original
    def test_status_change_recolors_existing_rows_without_rebuilding_the_tree(self):
        self.styling.update(self.styling.status.paths,{'a'},{'a','b'})
        self.assertFalse(self.delegate.is_empty(self.tree.indexFromItem(self.a)))
        self.assertTrue(self.delegate.is_empty(self.tree.indexFromItem(self.b)))
    def test_ambiguous_names_are_not_assigned_another_joints_status(self):
        item=QtWidgets.QTreeWidgetItem(self.tree,['joint'])
        self.assertIsNone(self.styling.status.resolve(self.tree.indexFromItem(item)))


if __name__=='__main__':unittest.main(verbosity=2)
