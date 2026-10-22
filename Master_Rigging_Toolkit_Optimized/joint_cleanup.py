"""Read-only skin influence audit and undoable pruning of unused joint branches.

No vertex weights are read. An influence with zero weights is still an influence.
Parents of retained DAG objects are kept rather than changing the rig hierarchy.
"""
import uuid

import maya.cmds as cmds


def _unique_node(value, kind=None):
    if not isinstance(value, str) or not value.strip() or "." in value:
        raise ValueError("Choose a scene object, not a component: {}".format(value))
    nodes = list(dict.fromkeys(cmds.ls(value.strip(), long=True, allPaths=True) or []))
    if len(nodes) != 1:
        raise ValueError("Object is missing, ambiguous or instanced: {}".format(value))
    node = nodes[0]
    if kind and cmds.nodeType(node) != kind:
        raise ValueError("Choose a {}: {}".format(kind, node))
    return node


def _identity(node):
    values = cmds.ls(node, uuid=True) or []
    if len(values) != 1:
        raise ValueError("Cannot identify object: {}".format(node))
    return values[0]


def _from_identity(identity):
    return _unique_node(identity)


def mesh_records(meshes):
    """Resolve mesh shapes/transforms; validate the entire input before returning."""
    if isinstance(meshes, str):
        meshes = [meshes]
    if not meshes:
        raise ValueError("Load at least one mesh.")
    records = {}
    for value in meshes:
        node = _unique_node(value)
        if cmds.nodeType(node) == "mesh":
            shapes = [node]
        elif cmds.nodeType(node) == "transform":
            shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True,
                                        fullPath=True, type="mesh") or []
        else:
            shapes = []
        shapes = [shape for shape in shapes
                  if not cmds.getAttr(shape + ".intermediateObject")]
        if not shapes:
            raise ValueError("No output polygon mesh on: {}".format(node))
        for shape in shapes:
            shape = _unique_node(shape, "mesh")
            identity = _identity(shape)
            records[identity] = {"uuid": identity, "path": shape}
    return list(records.values())


def joint_record(joint):
    node = _unique_node(joint, "joint")
    return {"uuid": _identity(node), "path": node}


def _skin_index():
    """One query per scene skinCluster, including skins outside the mesh input."""
    index = {}
    identities = {}
    skins = list(dict.fromkeys(cmds.ls(type="skinCluster") or []))
    for skin in skins:
        try:
            influences = cmds.skinCluster(skin, query=True, influence=True) or []
            for influence in influences:
                # A skin query returns the shortest UNIQUE name. Never compare
                # leaf names: duplicate names and namespaces are valid rigs.
                if influence not in identities:
                    identities[influence] = _identity(_unique_node(influence))
                index.setdefault(identities[influence], set()).add(skin)
        except (RuntimeError, ValueError) as exc:
            raise ValueError("Cannot inspect skinCluster '{}': {}. No deletion is allowed."
                             .format(skin, exc))
    return skins, index


def _node_protection(node, children):
    """Return a reason to keep the joint independently of skin membership."""
    if cmds.referenceQuery(node, isNodeReferenced=True):
        return "Referenced joint"
    if any(cmds.lockNode(node, query=True, lock=True) or []):
        return "Locked joint"
    try:
        _unique_node(_identity(node), "joint")
    except ValueError:
        return "Instanced joint"
    # Outgoing message / set / bind-pose links are bookkeeping. Any other
    # downstream consumer is kept. Child-joint inverseScale links disappear
    # naturally when eligible children are pruned first.
    edges = cmds.listConnections(node, source=False, destination=True,
                                 plugs=True, connections=True) or []
    if len(edges) % 2:
        raise ValueError("Cannot inspect outgoing connections on: {}".format(node))
    for source, destination in zip(edges[::2], edges[1::2]):
        if cmds.getAttr(source, type=True) == "message":
            continue
        destination_node = _unique_node(destination.split(".", 1)[0])
        if cmds.nodeType(destination_node) in ("dagPose", "objectSet", "displayLayer"):
            continue
        if destination_node in children and destination.split(".", 1)[1].startswith("inverseScale"):
            continue
        return "Drives {}".format(destination_node.rsplit("|", 1)[-1])
    return ""


def scan_unused_joints(meshes, root):
    """List hierarchy joints absent from the union of supplied mesh influences.

    The result is a snapshot with UUIDs, deletion reasons and safe branch counts.
    It does not write metadata, modify selection or create progress windows.
    """
    mesh_info = mesh_records(meshes)
    root_info = joint_record(root)
    selected_skins = set()
    unskinned = []
    for mesh in mesh_info:
        history = cmds.listHistory(mesh["path"], pruneDagObjects=True) or []
        skins = cmds.ls(history, type="skinCluster") if history else []
        mesh["skins"] = sorted(set(skins or []))
        selected_skins.update(mesh["skins"])
        if not mesh["skins"]:
            unskinned.append(mesh["path"])
    if not selected_skins:
        raise ValueError("No skinClusters found on the loaded meshes. Load a skinned mesh and scan again.")
    _skins, index = _skin_index()
    hierarchy = [root_info["path"]] + (cmds.listRelatives(
        root_info["path"], allDescendents=True, fullPath=True, type="joint") or [])
    hierarchy = sorted(set(hierarchy))
    rows = []
    by_path = {}
    bound_count = 0
    for joint in hierarchy:
        identity = _identity(joint)
        memberships = index.get(identity, set())
        if memberships.intersection(selected_skins):
            bound_count += 1
            continue
        children = cmds.listRelatives(joint, children=True, fullPath=True) or []
        elsewhere = sorted(memberships.difference(selected_skins))
        reason = ("Used by other skin: " + ", ".join(elsewhere)) if elsewhere else _node_protection(joint, children)
        row = {"uuid": identity, "path": joint, "children": children,
               "other_skins": elsewhere, "protection": reason,
               "can_delete": False, "can_prune": False, "reason": reason}
        rows.append(row)
        by_path[joint] = row
    # A retained child protects every ancestor. Branches whose children can ALL
    # be deleted are eligible for Delete All, in deepest-first order.
    for row in sorted(rows, key=lambda value: value["path"].count("|"), reverse=True):
        if row["protection"]:
            continue
        children = row["children"]
        row["can_delete"] = not children
        row["can_prune"] = all(child in by_path and by_path[child]["can_prune"] for child in children)
        row["reason"] = ("Ready to delete" if not children else
                         "Delete children first" if row["can_prune"] else "Keeps retained children")
    return {"meshes": mesh_info, "root": root_info,
            "skins": sorted(selected_skins), "unskinned_meshes": unskinned,
            "joint_count": len(hierarchy), "bound_count": bound_count,
            "rows": rows, "deletable_count": sum(row["can_prune"] for row in rows)}


def refresh_scan(snapshot):
    """Refresh by identity, so renamed/reparented inputs cannot target a namesake."""
    if not isinstance(snapshot, dict) or not snapshot.get("meshes") or not snapshot.get("root"):
        raise ValueError("Scan the meshes and joint root first.")
    meshes = [_from_identity(value["uuid"]) for value in snapshot["meshes"]]
    return scan_unused_joints(meshes, _from_identity(snapshot["root"]["uuid"]))


def delete_unused_joints(snapshot, joint_ids=None):
    """Delete only reviewed UUIDs that are still eligible; one atomic Undo action.

    Omit joint_ids for Delete All. A row action must supply one reviewed UUID.
    Newly created/unused joints since the displayed scan are never included.
    """
    reviewed = {row["uuid"] for row in snapshot.get("rows", [])}
    requested = reviewed if joint_ids is None else set(joint_ids)
    if not requested or not requested.issubset(reviewed):
        raise ValueError("Choose joints from the current scan results.")
    fresh = refresh_scan(snapshot)
    current = {row["uuid"]: row for row in fresh["rows"]}
    allowed = {key for key in requested if key in current and current[key]["can_prune"]}
    # A single row never deletes descendants as a side effect. In a batch, a
    # parent becomes eligible only if every current child is also in the batch.
    plan = []
    planned_paths = set()
    for key in sorted(allowed, key=lambda value: (current[value]["path"].count("|"), current[value]["path"]), reverse=True):
        row = current[key]
        if all(child in planned_paths for child in row["children"]):
            plan.append(row)
            planned_paths.add(row["path"])
    if not plan:
        return {"deleted": [], "skipped_count": len(requested), "scan": fresh}
    if not cmds.undoInfo(query=True, state=True):
        raise ValueError("Enable Maya Undo before deleting joints.")
    chunk = "CleanupUnusedJoints_" + uuid.uuid4().hex[:8]
    error = None
    deleted = []
    after = None
    cmds.undoInfo(openChunk=True, chunkName=chunk)
    try:
        for row in plan:
            node = _from_identity(row["uuid"])
            # Never ask Maya to delete a hierarchy. A new child or a protected
            # connection added by a scene callback stops and rolls back the batch.
            children = cmds.listRelatives(node, children=True, fullPath=True) or []
            reason = _node_protection(node, children)
            if children or reason:
                raise RuntimeError("Joint changed during deletion: {} ({})".format(node, reason or "has children"))
            # Recheck direct skin connections after earlier deletions/callbacks.
            if cmds.listConnections(node, source=False, destination=True, type="skinCluster"):
                raise RuntimeError("Joint gained a skinCluster connection: {}".format(node))
            cmds.delete(node)
            if cmds.ls(row["uuid"], long=True):
                raise RuntimeError("Maya did not delete: {}".format(node))
            deleted.append(row["path"])
        # Keep post-action validation in the transaction as well. An unexpected
        # inspection failure must not leave edits reported as a failed action.
        if cmds.ls(snapshot["root"]["uuid"], long=True):
            after = refresh_scan(snapshot)
    except Exception as exc:
        error = exc
    finally:
        cmds.undoInfo(closeChunk=True)
    if error is not None:
        # Empty chunks do not enter Maya's undo queue. Never undo a previous,
        # unrelated user operation when the very first delete was rejected.
        if cmds.undoInfo(query=True, undoName=True) == chunk:
            try:
                cmds.undo()
            except RuntimeError as rollback_error:
                raise RuntimeError("Cleanup failed and Maya could not undo it: {}. Original error: {}"
                                   .format(rollback_error, error)) from error
        raise RuntimeError("Cleanup stopped; its changes were rolled back: {}".format(error)) from error
    # Deleting an entirely unused hierarchy can legitimately remove the root.
    return {"deleted": deleted, "skipped_count": len(requested) - len(deleted), "scan": after}
