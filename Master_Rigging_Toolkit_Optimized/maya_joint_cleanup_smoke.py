"""Native Maya check: import maya_joint_cleanup_smoke; maya_joint_cleanup_smoke.run().

Creates a unique temporary namespace and deletes only those test nodes on exit.
Does not open a scene, reload plug-ins or clear the user's Undo queue.
"""
import uuid
import maya.cmds as cmds
import joint_cleanup


def run():
    if not cmds.undoInfo(query=True, state=True):
        raise RuntimeError("Enable Maya Undo before this test.")
    prefix = "rtkCleanupSmoke_" + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []

    def joint(name, parent=None):
        node = cmds.createNode("joint", name=prefix + ":" + name, skipSelect=True,
                               **({"parent": parent} if parent else {}))
        return (cmds.ls(node, long=True) or [node])[0]

    def row_map(report):
        return {row["uuid"]: row for row in report["rows"]}

    def identity(node):
        return cmds.ls(node, uuid=True)[0]

    def weights(skin, mesh):
        return [cmds.skinPercent(skin, mesh + ".vtx[{}]".format(i), query=True, value=True)
                for i in range(cmds.polyEvaluate(mesh, vertex=True))]

    try:
        cmds.namespace(setNamespace=":")
        cmds.namespace(addNamespace=prefix)
        root = joint("root")
        bound = joint("bound", root)
        cmds.setAttr(bound + ".translateX", 3)
        unused = joint("unused", root)
        tip = joint("unusedTip", unused)
        # Native parent scale / child inverseScale connections must not block
        # deleting an otherwise unused branch from the tips upward.
        if not cmds.isConnected(unused + ".scale", tip + ".inverseScale"):
            cmds.connectAttr(unused + ".scale", tip + ".inverseScale")
        zero = joint("zeroWeightInfluence", root)
        other_bound = joint("otherMeshInfluence", root)
        mesh = cmds.polyPlane(name=prefix + ":body", subdivisionsX=1, subdivisionsY=1)[0]
        skin = cmds.skinCluster(bound, mesh, toSelectedBones=True, name=prefix + ":bodySkin")[0]
        cmds.skinCluster(skin, edit=True, addInfluence=zero, weight=0.0)
        other_mesh = cmds.polyPlane(name=prefix + ":otherBody", subdivisionsX=1, subdivisionsY=1)[0]
        other_skin = cmds.skinCluster(other_bound, other_mesh, toSelectedBones=True, name=prefix + ":otherSkin")[0]
        assert set(cmds.skinCluster(skin, query=True, influence=True))
        before_matrix = cmds.xform(bound, query=True, worldSpace=True, matrix=True)
        bound_id = identity(bound)
        before_orientation = cmds.getAttr(bound + ".jointOrient")
        before_weights = weights(skin, mesh)
        before_other = weights(other_skin, other_mesh)
        report = joint_cleanup.scan_unused_joints([mesh], root)
        rows = row_map(report)
        assert identity(bound) not in rows and identity(zero) not in rows
        assert other_skin in rows[identity(other_bound)]["other_skins"]
        assert not rows[identity(root)]["can_prune"]
        assert report["deletable_count"] == 2
        tip_id, unused_id = identity(tip), identity(unused)

        single = joint_cleanup.delete_unused_joints(report, [tip_id])
        assert len(single["deleted"]) == 1 and not cmds.ls(tip_id, long=True)
        assert row_map(single["scan"])[unused_id]["can_delete"]
        cmds.undo()
        assert cmds.ls(tip_id, long=True)
        cmds.redo()
        assert not cmds.ls(tip_id, long=True)
        cmds.undo()

        # Old snapshots must still work after renaming their inputs.
        root = cmds.rename(root, prefix + ":renamedRoot")
        mesh = cmds.rename(mesh, prefix + ":renamedBody")
        bound = cmds.ls(bound_id, long=True)[0]
        result = joint_cleanup.delete_unused_joints(report)
        assert len(result["deleted"]) == 2
        assert not cmds.ls(tip_id, long=True) and not cmds.ls(unused_id, long=True)
        assert cmds.xform(bound, query=True, worldSpace=True, matrix=True) == before_matrix
        assert cmds.getAttr(bound + ".jointOrient") == before_orientation
        assert weights(skin, mesh) == before_weights
        assert weights(other_skin, other_mesh) == before_other
        cmds.undo()
        assert cmds.ls(tip_id, long=True) and cmds.ls(unused_id, long=True)
        cmds.redo()
        assert not cmds.ls(tip_id, long=True) and not cmds.ls(unused_id, long=True)
        print("PASS: cleanup membership, zero-weight influence, other skin protection, tip-first deletes, rename handling, skin/pose preservation and native Undo/Redo.")
    finally:
        cmds.namespace(setNamespace=":")
        members = cmds.ls(prefix + ":*", long=True) or []
        if members:
            cmds.delete(members)
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=namespace)
        surviving = [node for node in selection if cmds.objExists(node)]
        cmds.select(surviving, replace=True) if surviving else cmds.select(clear=True)
