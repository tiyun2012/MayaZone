"""Dependency-free cleanup orchestration checks; Maya itself is not emulated.

The command recorder models identity, child deletion and transaction snapshots
to check what operations the tool requests. Run the native smoke test in Maya
to validate Maya's solver, scene graph and Undo implementation.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


class CleanupCommands:
    def __init__(self):
        self.nodes = {}
        self.next_id = 0
        self.skins = {}
        self.history = {}
        self.edges = []
        self.selection = []
        self.calls = []
        self.skin_queries = []
        self.enabled = True
        self.chunks = []
        self.undo_stack = [("EarlierUserEdit", None)]
        self.redo_stack = []
        self.current = None
        self.fail_delete = set()
        self.after_delete = None
        self.add("|body", "transform")
        self.mesh = self.add("|body|bodyShape", "mesh")
        self.root = self.add("|root", "joint")
        self.bound = self.add("|root|bound", "joint")
        self.branch = self.add("|root|unused", "joint")
        self.tip = self.add("|root|unused|tip", "joint")
        self.skin("bodySkin", [self.bound], [self.mesh])

    def add(self, node, kind, **attrs):
        self.nodes[node] = {"type": kind, "uuid": "uid" + str(self.next_id),
                            "locked": False, "referenced": False, "instanced": False,
                            "intermediate": False, **attrs}
        self.next_id += 1
        return node

    def skin(self, name, influences, meshes):
        if name not in self.nodes:
            self.add(name, "skinCluster")
        self.skins[name] = list(influences)
        for mesh in meshes:
            self.history.setdefault(mesh, []).append(name)

    def uid(self, node):
        return self.nodes[node]["uuid"]

    def ls(self, value=None, **kw):
        if kw.get("selection"):
            values = list(self.selection)
        elif value is None:
            values = list(self.nodes)
        else:
            args = value if isinstance(value, (tuple, list)) else [value]
            values = []
            for arg in args:
                values.extend(n for n, data in self.nodes.items()
                              if n == arg or data["uuid"] == arg or n.rsplit("|", 1)[-1] == arg)
            values = list(dict.fromkeys(values))
        if kw.get("type"):
            values = [n for n in values if self.nodes[n]["type"] == kw["type"]]
        if kw.get("uuid"):
            return [self.nodes[n]["uuid"] for n in values]
        if kw.get("allPaths"):
            values += ["|instance" + n for n in list(values) if self.nodes[n]["instanced"]]
        return values

    def nodeType(self, node):
        return self.nodes[node]["type"]

    def getAttr(self, plug, **kw):
        if kw.get("type"):
            return "message" if plug.split(".", 1)[1] == "message" else "matrix"
        node, attr = plug.split(".", 1)
        if attr == "intermediateObject":
            return self.nodes[node]["intermediate"]
        raise AssertionError("Unexpected attribute query: " + plug)

    def listRelatives(self, node, **kw):
        if kw.get("allDescendents"):
            result = [n for n in self.nodes if n.startswith(node + "|")]
        else:
            result = [n for n in self.nodes if n.rsplit("|", 1)[0] == node]
        if kw.get("shapes"):
            result = [n for n in result if self.nodes[n]["type"] == "mesh"]
        if kw.get("noIntermediate"):
            result = [n for n in result if not self.nodes[n]["intermediate"]]
        if kw.get("type"):
            result = [n for n in result if self.nodes[n]["type"] == kw["type"]]
        return result

    def listHistory(self, node, **kw):
        return self.history.get(node, [])

    def skinCluster(self, skin, **kw):
        assert kw == {"query": True, "influence": True}, "Only influence membership may be queried"
        self.skin_queries.append(skin)
        result = self.skins[skin]
        if isinstance(result, Exception):
            raise result
        return list(result)

    def referenceQuery(self, node, **kw):
        return self.nodes[node]["referenced"]

    def lockNode(self, node, **kw):
        return [self.nodes[node]["locked"]]

    def listConnections(self, node, **kw):
        outgoing = [(a, b) for a, b in self.edges if a.split(".", 1)[0] == node]
        if kw.get("type") == "skinCluster":
            return [name for name, influences in self.skins.items()
                    if isinstance(influences, list) and node in influences]
        return [plug for pair in outgoing for plug in pair]

    def _state(self):
        return copy.deepcopy((self.nodes, self.skins, self.history, self.edges))

    def undoInfo(self, **kw):
        if kw.get("query"):
            if kw.get("state"):
                return self.enabled
            if kw.get("undoName"):
                return self.undo_stack[-1][0] if self.undo_stack else ""
        elif kw.get("openChunk"):
            assert self.current is None
            self.current = (kw["chunkName"], self._state())
            self.chunks.append("open")
        elif kw.get("closeChunk"):
            name, state = self.current
            if state != self._state():
                self.undo_stack.append((name, state))
            self.current = None
            self.chunks.append("close")

    def undo(self):
        name, state = self.undo_stack.pop()
        self.calls.append(("undo", name))
        if state is None:
            raise AssertionError("An unrelated user operation was undone")
        self.redo_stack.append((name, self._state()))
        self.nodes, self.skins, self.history, self.edges = copy.deepcopy(state)

    def redo(self):
        name, state = self.redo_stack.pop()
        self.undo_stack.append((name, self._state()))
        self.nodes, self.skins, self.history, self.edges = copy.deepcopy(state)

    def delete(self, node):
        self.calls.append(("delete", node))
        if node in self.fail_delete:
            raise RuntimeError("Recorded delete failure")
        doomed = [n for n in self.nodes if n == node or n.startswith(node + "|")]
        for n in doomed:
            del self.nodes[n]
        self.edges = [(a, b) for a, b in self.edges
                      if a.split(".", 1)[0] not in doomed and b.split(".", 1)[0] not in doomed]
        if self.after_delete:
            self.after_delete(node)

    def rename(self, old, new):
        changes = {n: new + n[len(old):] for n in self.nodes if n == old or n.startswith(old + "|")}
        self.nodes = {changes.get(n, n): data for n, data in self.nodes.items()}
        self.skins = {n: [changes.get(v, v) for v in values] for n, values in self.skins.items()}
        self.history = {changes.get(n, n): values for n, values in self.history.items()}
        self.edges = [(changes.get(a.split(".", 1)[0], a.split(".", 1)[0]) + "." + a.split(".", 1)[1],
                       changes.get(b.split(".", 1)[0], b.split(".", 1)[0]) + "." + b.split(".", 1)[1])
                      for a, b in self.edges]

    def internalVar(self, **kw):
        return ""

    def select(self, nodes, **kw):
        self.selection = [nodes] if isinstance(nodes, str) else list(nodes)

    def warning(self, message):
        self.calls.append(("warning", message))


def load_backend(commands):
    maya = types.ModuleType("maya")
    maya.cmds = commands
    spec = importlib.util.spec_from_file_location("joint_cleanup_under_test", Path(__file__).with_name("joint_cleanup.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"maya": maya, "maya.cmds": commands}):
        spec.loader.exec_module(module)
    return module


class JointCleanupTests(unittest.TestCase):
    def setUp(self):
        self.cmds = CleanupCommands()
        self.tool = load_backend(self.cmds)

    def scan(self, meshes=None, root=None):
        return self.tool.scan_unused_joints(meshes or [self.cmds.mesh], root or self.cmds.root)

    def rows(self, report):
        return {row["path"]: row for row in report["rows"]}

    def test_read_only_scan_and_influence_membership(self):
        self.cmds.selection = [self.cmds.bound]
        before = self.cmds._state()
        report = self.scan()
        self.assertEqual(report["bound_count"], 1)
        self.assertEqual(set(self.rows(report)), {self.cmds.root, self.cmds.branch, self.cmds.tip})
        self.assertEqual(self.cmds._state(), before)
        self.assertEqual(self.cmds.selection, [self.cmds.bound])
        self.assertEqual(self.cmds.calls, [])
        self.assertEqual(self.cmds.chunks, [])

    def test_zero_weight_influence_is_still_kept(self):
        # No weight data exists in this command recorder. Influence membership
        # alone must keep a joint; weightedInfluence/skinPercent is never called.
        self.cmds.skins["bodySkin"].append(self.cmds.tip)
        report = self.scan()
        self.assertNotIn(self.cmds.tip, self.rows(report))
        self.assertEqual(report["deletable_count"], 0)

    def test_union_of_multiple_meshes_and_skins(self):
        mesh = self.cmds.add("|headShape", "mesh")
        self.cmds.skin("headSkin", [self.cmds.tip], [mesh])
        report = self.scan([self.cmds.mesh, mesh])
        self.assertEqual(report["skins"], ["bodySkin", "headSkin"])
        self.assertNotIn(self.cmds.tip, self.rows(report))
        self.assertEqual(self.cmds.skin_queries, ["bodySkin", "headSkin"])

    def test_all_skinclusters_in_mesh_history_are_checked(self):
        self.cmds.skin("secondSkin", [self.cmds.branch], [self.cmds.mesh])
        self.assertNotIn(self.cmds.branch, self.rows(self.scan()))

    def test_duplicate_mesh_transform_shape_inputs_are_deduplicated(self):
        report = self.scan(["|body", self.cmds.mesh, "|body"])
        self.assertEqual(len(report["meshes"]), 1)
        self.assertEqual(self.cmds.skin_queries, ["bodySkin"])

    def test_intermediate_mesh_is_not_an_input(self):
        self.cmds.add("|body|orig", "mesh", intermediate=True)
        self.assertEqual(len(self.tool.mesh_records(["|body"])), 1)
        with self.assertRaisesRegex(ValueError, "No output"):
            self.tool.mesh_records(["|body|orig"])

    def test_empty_meshes_missing_mesh_and_components_fail(self):
        for value in ([], ["missing"], [self.cmds.mesh + ".vtx[0]"], [self.cmds.root]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.tool.scan_unused_joints(value, self.cmds.root)
        self.assertEqual(self.cmds.calls, [])

    def test_root_must_be_a_single_joint(self):
        with self.assertRaisesRegex(ValueError, "Choose a joint"):
            self.scan(root="|body")
        self.cmds.add("|other|root", "joint")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.scan(root="root")

    def test_unskinned_only_inputs_never_offer_all_joints(self):
        mesh = self.cmds.add("|unskinned", "mesh")
        with self.assertRaisesRegex(ValueError, "No skinClusters"):
            self.scan([mesh])
        self.assertEqual(self.cmds.calls, [])

    def test_mixed_unskinned_inputs_are_reported(self):
        mesh = self.cmds.add("|unskinned", "mesh")
        self.assertEqual(self.scan([mesh, self.cmds.mesh])["unskinned_meshes"], [mesh])

    def test_outside_skin_and_its_parent_are_protected(self):
        other = self.cmds.add("|otherShape", "mesh")
        self.cmds.skin("otherSkin", [self.cmds.tip], [other])
        rows = self.rows(self.scan())
        self.assertIn("otherSkin", rows[self.cmds.tip]["reason"])
        self.assertFalse(rows[self.cmds.branch]["can_prune"])

    def test_joint_identity_ignores_duplicate_leaf_names_and_namespaces(self):
        duplicate = self.cmds.add("|other|bound", "joint")
        namespaced = self.cmds.add("|root|char:bound", "joint")
        rows = self.rows(self.scan())
        self.assertNotIn(self.cmds.bound, rows)
        self.assertIn(namespaced, rows)
        self.assertNotIn(duplicate, rows)

    def test_locked_or_referenced_tips_keep_their_branch(self):
        for attribute in ("locked", "referenced"):
            with self.subTest(attribute=attribute):
                self.cmds.nodes[self.cmds.tip][attribute] = True
                rows = self.rows(self.scan())
                self.assertFalse(rows[self.cmds.tip]["can_delete"])
                self.assertFalse(rows[self.cmds.branch]["can_prune"])
                self.cmds.nodes[self.cmds.tip][attribute] = False

    def test_instanced_joints_are_protected(self):
        self.cmds.nodes[self.cmds.tip]["instanced"] = True
        self.assertEqual(self.rows(self.scan())[self.cmds.tip]["reason"], "Instanced joint")

    def test_non_joint_child_protects_unused_joint(self):
        self.cmds.add(self.cmds.tip + "|locator", "transform")
        self.assertEqual(self.scan()["deletable_count"], 0)

    def test_unused_parent_of_skinned_joint_is_retained(self):
        rows = self.rows(self.scan())
        self.assertEqual(rows[self.cmds.root]["reason"], "Keeps retained children")
        self.assertFalse(rows[self.cmds.root]["can_prune"])

    def test_rig_driver_connection_protects_joint(self):
        consumer = self.cmds.add("someConstraint", "parentConstraint")
        self.cmds.edges.append((self.cmds.tip + ".worldMatrix[0]", consumer + ".target[0].targetParentMatrix"))
        self.assertEqual(self.scan()["deletable_count"], 0)

    def test_bind_pose_and_message_links_do_not_block_cleanup(self):
        self.cmds.add("bindPose", "dagPose")
        self.cmds.add("rigMetadata", "network")
        self.cmds.edges.extend([(self.cmds.tip + ".worldMatrix[0]", "bindPose.worldMatrix[0]"),
                                (self.cmds.tip + ".message", "rigMetadata.member")])
        self.assertTrue(self.rows(self.scan())[self.cmds.tip]["can_delete"])

    def test_child_inverse_scale_links_allow_bottom_up_branch_cleanup(self):
        self.cmds.edges.append((self.cmds.branch + ".scale", self.cmds.tip + ".inverseScale"))
        report = self.scan()
        self.assertEqual(report["deletable_count"], 2)
        result = self.tool.delete_unused_joints(report)
        self.assertEqual(result["deleted"], [self.cmds.tip, self.cmds.branch])

    def test_delete_one_row_does_not_delete_children(self):
        report = self.scan()
        result = self.tool.delete_unused_joints(report, [self.cmds.uid(self.cmds.branch)])
        self.assertEqual(result["deleted"], [])
        self.assertIn(self.cmds.tip, self.cmds.nodes)
        self.assertEqual(self.cmds.chunks, [])

    def test_delete_one_tip_refreshes_parent_status(self):
        result = self.tool.delete_unused_joints(self.scan(), [self.cmds.uid(self.cmds.tip)])
        self.assertEqual(result["deleted"], [self.cmds.tip])
        self.assertTrue(self.rows(result["scan"])[self.cmds.branch]["can_delete"])
        self.assertEqual(self.cmds.chunks, ["open", "close"])

    def test_delete_all_prunes_tips_first_one_undo_and_preserves_bound_joint(self):
        before = self.cmds._state()
        result = self.tool.delete_unused_joints(self.scan())
        self.assertEqual(result["deleted"], [self.cmds.tip, self.cmds.branch])
        self.assertEqual(result["skipped_count"], 1)
        self.assertIn(self.cmds.bound, self.cmds.nodes)
        self.assertIn(self.cmds.root, self.cmds.nodes)
        self.assertEqual(self.cmds.chunks, ["open", "close"])
        self.cmds.undo()
        self.assertEqual(self.cmds._state(), before)
        self.cmds.redo()
        self.assertNotIn(self.cmds.branch, self.cmds.nodes)

    def test_fully_unused_root_can_be_removed(self):
        root = self.cmds.add("|entirelyUnused", "joint")
        tip = self.cmds.add(root + "|tip", "joint")
        result = self.tool.delete_unused_joints(self.scan(root=root))
        self.assertEqual(result["deleted"], [tip, root])
        self.assertIsNone(result["scan"])

    def test_all_bound_hierarchy_has_no_candidates(self):
        self.cmds.skins["bodySkin"] = [self.cmds.root, self.cmds.bound, self.cmds.branch, self.cmds.tip]
        report = self.scan()
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["deletable_count"], 0)

    def test_joint_newly_bound_after_scan_is_kept(self):
        report = self.scan()
        self.cmds.skins["bodySkin"].append(self.cmds.tip)
        self.assertEqual(self.tool.delete_unused_joints(report)["deleted"], [])
        self.assertIn(self.cmds.tip, self.cmds.nodes)

    def test_new_unreviewed_joint_is_not_deleted_and_protects_its_parent(self):
        report = self.scan()
        self.cmds.add(self.cmds.branch + "|newTip", "joint")
        result = self.tool.delete_unused_joints(report)
        self.assertEqual(result["deleted"], [self.cmds.tip])
        self.assertIn(self.cmds.branch, self.cmds.nodes)

    def test_renamed_inputs_and_joints_resolve_by_uuid(self):
        report = self.scan()
        self.cmds.rename("|body", "|renamedMesh")
        self.cmds.rename(self.cmds.root, "|renamedRoot")
        result = self.tool.delete_unused_joints(report)
        self.assertEqual(len(result["deleted"]), 2)
        self.assertEqual(result["scan"]["root"]["path"], "|renamedRoot")

    def test_joint_moved_outside_root_is_not_deleted(self):
        report = self.scan()
        self.cmds.rename(self.cmds.tip, "|movedTip")
        result = self.tool.delete_unused_joints(report)
        self.assertNotIn("|movedTip", result["deleted"])
        self.assertIn("|movedTip", self.cmds.nodes)

    def test_deleted_mesh_input_aborts_without_editing(self):
        report = self.scan()
        del self.cmds.nodes[self.cmds.mesh]
        with self.assertRaisesRegex(ValueError, "missing"):
            self.tool.delete_unused_joints(report)
        self.assertEqual(self.cmds.calls, [])

    def test_unknown_review_id_never_mutates_scene(self):
        with self.assertRaises(ValueError):
            self.tool.delete_unused_joints(self.scan(), ["unreviewed"])
        self.assertEqual(self.cmds.calls, [])

    def test_disabled_undo_blocks_deletion(self):
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError, "Enable Maya Undo"):
            self.tool.delete_unused_joints(self.scan())
        self.assertEqual(self.cmds.calls, [])

    def test_second_delete_failure_rolls_back_whole_batch(self):
        before = self.cmds._state()
        self.cmds.fail_delete.add(self.cmds.branch)
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            self.tool.delete_unused_joints(self.scan())
        self.assertEqual(self.cmds._state(), before)
        self.assertEqual(self.cmds.chunks, ["open", "close"])
        self.assertEqual(self.cmds.undo_stack[-1][0], "EarlierUserEdit")

    def test_first_delete_failure_never_undoes_previous_user_edit(self):
        self.cmds.fail_delete.add(self.cmds.tip)
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            self.tool.delete_unused_joints(self.scan())
        self.assertFalse(any(call[0] == "undo" for call in self.cmds.calls))
        self.assertEqual(self.cmds.undo_stack[-1][0], "EarlierUserEdit")

    def test_new_child_during_batch_stops_and_rolls_back(self):
        before = self.cmds._state()
        self.cmds.after_delete = lambda node: self.cmds.add(self.cmds.branch + "|newChild", "joint")
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            self.tool.delete_unused_joints(self.scan())
        self.assertEqual(self.cmds._state(), before)

    def test_new_skin_connection_during_batch_stops_and_rolls_back(self):
        before = self.cmds._state()
        self.cmds.after_delete = lambda node: self.cmds.skins["bodySkin"].append(self.cmds.branch)
        with self.assertRaisesRegex(RuntimeError, "skinCluster connection"):
            self.tool.delete_unused_joints(self.scan())
        self.assertEqual(self.cmds._state(), before)

    def test_unreadable_other_skin_aborts_instead_of_assuming_unused(self):
        self.cmds.skin("brokenSkin", [], [])
        self.cmds.skins["brokenSkin"] = RuntimeError("not readable")
        with self.assertRaisesRegex(ValueError, "Cannot inspect skinCluster"):
            self.scan()
        self.assertEqual(self.cmds.calls, [])

    def test_post_delete_scan_failure_also_rolls_back(self):
        before = self.cmds._state()
        self.cmds.after_delete = lambda node: self.cmds.skins.__setitem__("bodySkin", RuntimeError("not readable"))
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            self.tool.delete_unused_joints(self.scan(), [self.cmds.uid(self.cmds.tip)])
        self.assertEqual(self.cmds._state(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
