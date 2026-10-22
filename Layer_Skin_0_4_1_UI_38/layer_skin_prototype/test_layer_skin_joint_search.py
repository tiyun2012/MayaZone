"""Wildcard hierarchy filtering with real Qt rows and a scene command adapter."""
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
class JointSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.api=JointSceneAPI()
        self.extra=['|joint1|joint2|rig:leftArmShoulder',
                    '|joint1|joint2|rig:leftArmShoulder|finger',
                    '|joint1|joint2|rig:leftLegShoulder',
                    '|joint1|joint2|rig:rightArmShoulder',
                    '|joint1|joint2|rig:leftElbow']
        for i,path in enumerate(self.extra):
            self.api.joint_paths.append(path);self.api.path_ids[path]='search-joint-'+str(i)
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh')
        self.window.show();self.window.refresh();self.app.processEvents()
        self.browser=self.window.browser

    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)

    def visible(self):return {path for path,item in self.browser.items.items() if not item.isHidden()}

    def test_search_is_above_the_tree_and_has_a_clear_button(self):
        search=self.browser.search;tree=self.browser.widget
        self.assertIs(self.window.findChild(QtWidgets.QLineEdit,'LayerSkinJointSearch'),search)
        self.assertTrue(search.isClearButtonEnabled())
        self.assertLess(search.mapTo(self.window,QtCore.QPoint()).y(),tree.mapTo(self.window,QtCore.QPoint()).y())
        self.assertIn('left*Shoulder*',search.placeholderText())

    def test_plain_text_and_repeated_wildcards_match_case_insensitively(self):
        parents=set(self.api.joint_paths[:2])
        for pattern,matched in (
            ('left**Shoulder**',{self.extra[0],self.extra[2]}),
            ('LEFT*shoulder*',{self.extra[0],self.extra[2]}),
            ('shoulder',{self.extra[0],self.extra[2],self.extra[3]}),
            ('left?rmShoulder',{self.extra[0]}),
            ('rig:left*Shoulder*',{self.extra[0],self.extra[2]}),
        ):
            with self.subTest(pattern=pattern):
                self.browser.search.setText(pattern)
                self.assertEqual(self.visible(),parents|matched)
                self.assertTrue(self.browser.items[self.api.joint_paths[0]].isExpanded())
                self.assertTrue(self.browser.items[self.api.joint_paths[1]].isExpanded())
                self.assertIn('{} of 8 joints match'.format(len(matched)),self.browser.search_status.text())

    def test_matching_parent_does_not_unfilter_its_nonmatching_children(self):
        self.browser.search.setText('leftArmShoulder')
        self.assertFalse(self.browser.items[self.extra[0]].isHidden())
        self.assertTrue(self.browser.items[self.extra[1]].isHidden())

    def test_clear_restores_expansion_selection_and_all_rows(self):
        parent=self.api.joint_paths[1]
        self.window.choose_joint(self.api.joint_paths[2])
        self.browser.items[parent].setExpanded(False)
        expanded={path:item.isExpanded() for path,item in self.browser.items.items()}
        before=self.api.snapshot();selected=self.browser.joints();active=self.window.active_joint()
        self.browser.search.setText('left*Shoulder*')
        self.assertEqual(self.browser.joints(),selected)
        self.assertEqual(self.window.active_joint(),active)
        self.browser.search.clear()
        self.assertEqual(self.visible(),set(self.browser.items))
        self.assertEqual({path:item.isExpanded() for path,item in self.browser.items.items()},expanded)
        self.assertEqual(self.browser.joints(),selected)
        self.assertEqual(self.api.snapshot(),before)
        self.assertFalse(self.browser.search_status.isVisible())

    def test_no_matches_explains_empty_view_and_keeps_target(self):
        selected=self.browser.joints();active=self.window.active_joint()
        self.browser.search.setText('missing*Shoulder*')
        self.assertFalse(self.visible());self.assertTrue(self.browser.search_status.isVisible())
        self.assertEqual(self.browser.search_status.text(),'No matching joints.')
        self.assertEqual(self.browser.joints(),selected)
        self.assertEqual(self.window.active_joint(),active)

    def test_search_reads_only_existing_qt_rows_and_keeps_pending_paint(self):
        self.window.choose_joint(self.api.joint_paths[2]);self.window.paint()
        self.window.session.initialize('meshShape');self.window.session.set_value(1,0,.65)
        before=self.api.snapshot();calls=len(self.api.calls);stroke=self.window.session.stroke
        with (mock.patch.object(self.api.cmds,'ls',side_effect=AssertionError('search queried Maya')),
              mock.patch.object(self.api.cmds,'nodeType',side_effect=AssertionError('search queried Maya')),
              mock.patch.object(self.api.cmds,'listRelatives',side_effect=AssertionError('search queried Maya'))):
            self.browser.search.setText('left*Shoulder*');self.browser.search.setText('missing');self.browser.search.clear()
        self.assertIs(self.window.session.stroke,stroke)
        self.assertTrue(self.window.session.active)
        self.assertEqual(self.window.session.get_value(1,0),.65)
        self.assertEqual(len(self.api.calls),calls);self.assertEqual(self.api.snapshot(),before)

    def test_rebuild_reapplies_search_and_restores_unfiltered_branch_state(self):
        parent=self.api.joint_paths[1];self.browser.items[parent].setExpanded(False)
        self.browser.search.setText('left*Shoulder*')
        added='|joint1|joint2|leftNewShoulder';self.api.joint_paths.append(added);self.api.path_ids[added]='added'
        self.window.refresh(force_browser=True)
        self.assertEqual(self.browser.search.text(),'left*Shoulder*')
        self.assertIn(added,self.visible());self.assertIn('3 of 9 joints match',self.browser.search_status.text())
        self.browser.search.clear();self.assertFalse(self.browser.items[parent].isExpanded())

    def test_hidden_multiselection_is_retained_through_filter_and_rebuild(self):
        paths=[self.api.joint_paths[2],self.extra[0]]
        self.browser.widget.clearSelection()
        for path in paths:self.browser.items[path].setSelected(True)
        self.browser.search.setText('right*Shoulder*')
        self.assertEqual(set(self.browser.joints()),set(paths))
        self.window.refresh(force_browser=True)
        self.assertEqual(set(self.browser.joints()),set(paths))
        self.browser.search.clear();self.assertEqual(set(self.browser.joints()),set(paths))

    def test_filtered_row_is_paintable_and_padlock_still_toggles(self):
        path=self.extra[0];self.browser.search.setText('leftArmShoulder')
        item=self.browser.items[path];tree=self.browser.widget
        QtTest.QTest.mouseClick(tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,
                               tree.visualItemRect(item).center())
        self.assertEqual(self.window.active_joint(),self.api.path_ids[path])
        self.assertTrue(self.browser.styling.delegates[0].is_empty(tree.indexFromItem(item)))
        QtTest.QTest.mouseClick(tree.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,
                               self.browser.lock_rect(item).center())
        self.assertIn(self.api.path_ids[path],self.browser.locked)
        self.assertEqual(self.browser.search.text(),'leftArmShoulder')
        self.assertFalse(self.browser.items[path].isHidden())


if __name__=='__main__':unittest.main(verbosity=2)
