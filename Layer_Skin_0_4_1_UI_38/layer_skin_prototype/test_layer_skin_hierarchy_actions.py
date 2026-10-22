"""Real Qt branch gestures, inclusive selection and paint-session preservation."""
import unittest
from unittest import mock

from test_layer_skin_ui import JointSceneAPI, ui

if ui is not None:
    QtCore,QtWidgets=ui.QtCore,ui.QtWidgets
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest


@unittest.skipIf(ui is None,'PySide is required')
class HierarchyActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.api=JointSceneAPI()
        self.extra=['|joint1|joint2|bufferA|same',
                    '|joint1|joint2|bufferA|same|tip',
                    '|joint1|joint2|bufferB|same',
                    '|joint1|joint2|bufferB|same|tip',
                    '|joint1|joint20','|joint1|joint20|tip']
        for i,path in enumerate(self.extra):
            self.api.joint_paths.append(path);self.api.path_ids[path]='branch-joint-'+str(i)
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh')
        self.window.show();self.window.refresh();self.app.processEvents()
        self.browser=self.window.browser;self.tree=self.browser.widget
        self.root='|joint1|joint2';self.other='|joint1|joint20'

    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)

    def branch(self,path):return {p for p in self.browser.items if p==path or p.startswith(path+'|')}

    def collapse(self,path):
        for candidate in self.branch(path):self.browser.items[candidate].setExpanded(False)

    def click(self,path,modifiers=QtCore.Qt.NoModifier,arrow=False):
        item=self.browser.items[path];rect=self.tree.visualItemRect(item)
        point=QtCore.QPoint(rect.left()-self.tree.indentation()//2,rect.center().y()) if arrow else rect.center()
        QtTest.QTest.mouseClick(self.tree.viewport(),QtCore.Qt.LeftButton,modifiers,point)

    def assert_expanded(self,path):
        for candidate in self.branch(path):
            item=self.browser.items[candidate]
            if item.childCount():self.assertTrue(item.isExpanded(),candidate)

    def test_shift_row_opens_all_levels_and_only_the_clicked_branch(self):
        self.collapse(self.root);self.collapse(self.other)
        self.click(self.root,QtCore.Qt.ShiftModifier)
        self.assert_expanded(self.root);self.assertFalse(self.browser.items[self.other].isExpanded())
        self.assertEqual(self.browser.joints(),[self.root])
        self.assertEqual(self.window.active_joint(),self.api.path_ids[self.root])
        self.assertEqual(self.api.selected,['mesh']);self.assertEqual(self.api.calls,[])

    def test_shift_arrow_keeps_branch_open_on_release_and_repeated_clicks(self):
        self.window.choose_joint(self.root);self.collapse(self.root)
        for _ in range(2):
            self.click(self.root,QtCore.Qt.ShiftModifier,arrow=True)
            self.assert_expanded(self.root);self.assertEqual(self.browser.joints(),[self.root])
        self.click(self.root,arrow=True)
        self.assertFalse(self.browser.items[self.root].isExpanded())

    def test_shift_existing_selection_preserves_other_selected_joints(self):
        self.click(self.root);self.click(self.other,QtCore.Qt.ControlModifier)
        before=set(self.browser.joints());self.collapse(self.root)
        self.click(self.root,QtCore.Qt.ShiftModifier)
        self.assertEqual(set(self.browser.joints()),before)
        self.assertEqual(self.browser.joints()[-1],self.root);self.assert_expanded(self.root)

    def test_control_shift_adds_a_branch_root_without_selecting_a_range(self):
        self.click(self.other);self.collapse(self.root)
        self.click(self.root,QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
        self.assertEqual(set(self.browser.joints()),{self.root,self.other});self.assert_expanded(self.root)

    def test_shift_padlock_still_only_toggles_the_lock(self):
        self.window.choose_joint(self.other);self.collapse(self.root)
        item=self.browser.items[self.root];selected=self.browser.joints()
        QtTest.QTest.mouseClick(self.tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.ShiftModifier,
                               self.browser.lock_rect(item).center())
        self.assertIn(self.api.path_ids[self.root],self.browser.locked)
        self.assertEqual(self.browser.joints(),selected)
        self.assertFalse(item.isExpanded())

    def test_branch_button_is_inclusive_and_crosses_transform_buffers(self):
        self.window.choose_joint(self.root);self.collapse(self.root)
        current=self.tree.currentItem();before=self.api.snapshot()
        self.browser.select_branch.click()
        self.assertEqual(set(self.browser.joints()),self.branch(self.root))
        self.assertIn(self.root,self.browser.joints());self.assertIs(self.tree.currentItem(),current)
        self.assertNotIn(self.other,self.browser.joints());self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(self.api.selected,['mesh']);self.assertFalse(self.browser.items[self.root].isExpanded())

    def test_branch_button_includes_search_hidden_children_and_keeps_filter(self):
        self.window.choose_joint(self.root);self.browser.search.setText('joint2')
        self.assertTrue(self.browser.items[self.extra[0]].isHidden())
        self.browser.select_branch.click()
        self.assertEqual(set(self.browser.joints()),self.branch(self.root))
        self.assertEqual(self.browser.search.text(),'joint2')
        self.assertTrue(self.browser.items[self.extra[0]].isHidden())
        self.browser.search.clear();self.assertEqual(set(self.browser.joints()),self.branch(self.root))
        self.assertEqual(self.window.active_joint(),self.api.path_ids[self.root])

    def test_multiple_overlapping_roots_select_once_and_keep_current_paint_target(self):
        tip=self.extra[1]
        self.click(self.root);self.click(tip,QtCore.Qt.ControlModifier);self.click(self.other,QtCore.Qt.ControlModifier)
        callback=mock.Mock(wraps=self.browser.selected);self.browser.selected=callback
        self.browser.select_branch.click()
        self.assertEqual(set(self.browser.joints()),self.branch(self.root)|self.branch(self.other))
        self.assertEqual(self.browser.joints()[-1],self.other);self.assertEqual(callback.call_count,1)
        self.browser.select_branch.click();self.assertEqual(callback.call_count,1)

    def test_expand_and_select_branch_preserve_pending_paint_and_feedback(self):
        self.window.choose_joint(self.root);self.window.paint();session=self.window.session
        session.initialize('meshShape');session.set_value(1,0,.65)
        stroke=session.stroke;before=self.api.snapshot();calls=len(self.api.calls)
        with mock.patch.object(session,'start',wraps=session.start) as restart:
            self.collapse(self.root);self.click(self.root,QtCore.Qt.ShiftModifier)
            self.browser.select_branch.click()
        self.assertFalse(restart.called);self.assertIs(session.stroke,stroke)
        self.assertEqual(session.get_value(1,0),.65);self.assertTrue(session.active)
        self.assertEqual(session.joint,self.api.path_ids[self.root]);self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(len(self.api.calls),calls);self.assertEqual(self.api.selected,['mesh'])

    def test_shift_new_joint_commits_previous_paint_once_and_keeps_it_on_return(self):
        tip=self.api.joint_paths[2];self.window.choose_joint(tip);self.window.paint()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.7)
        self.collapse(self.root);self.click(self.root,QtCore.Qt.ShiftModifier)
        self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.window.session.joint,self.api.path_ids[self.root])
        self.window.choose_joint(tip);self.assertEqual(self.window.session.values,[.7,0.,0.])

    def test_filtered_expansion_survives_clearing_search_and_rebuilding(self):
        self.window.choose_joint(self.root);self.collapse(self.root)
        self.browser.search.setText('joint2')
        self.click(self.root,QtCore.Qt.ShiftModifier);self.browser.search.clear()
        self.assert_expanded(self.root)
        self.window.refresh(force_browser=True);self.assert_expanded(self.root)

    def test_branch_actions_use_cached_rows_and_disabled_button_handles_no_selection(self):
        self.window.choose_joint(self.root);self.browser.selected=mock.Mock()
        with (mock.patch.object(self.api.cmds,'ls',side_effect=AssertionError('DAG query')),
              mock.patch.object(self.api.cmds,'nodeType',side_effect=AssertionError('DAG query')),
              mock.patch.object(self.api.cmds,'listRelatives',side_effect=AssertionError('DAG query'))):
            self.collapse(self.root);self.click(self.root,QtCore.Qt.ShiftModifier)
            self.browser.select_branch.click()
        self.assertEqual(set(self.browser.joints()),self.branch(self.root))
        self.tree.clearSelection();self.assertFalse(self.browser.select_branch.isEnabled())
        self.browser.select_branch.click();self.assertEqual(self.browser.joints(),[])
        self.window.choose_joint(self.root);self.assertTrue(self.browser.select_branch.isEnabled())


if __name__=='__main__':unittest.main(verbosity=2)
