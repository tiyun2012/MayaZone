"""Select the PoseDriver cone and run this entire file in Maya's Python editor.
Read-only: queries scene data; creates, edits and deletes nothing.
Does not require importing or reloading the rigging toolkit.
"""
import json
import math
import maya.cmds as cmds
import maya.api.OpenMaya as om


def _pd_diag_node(identity):
    nodes = cmds.ls(identity, long=True) or []
    if len(nodes) != 1:
        raise ValueError("Missing or ambiguous setup member: " + str(identity))
    return nodes[0]


def _pd_diag_get(plug):
    try:
        return cmds.getAttr(plug)
    except RuntimeError as exc:
        return {"error": str(exc)}


def _pd_diag_source(plug):
    sources = cmds.listConnections(plug, source=True, destination=False,
                                   plugs=True, skipConversionNodes=True) or []
    return sources[0] if len(sources) == 1 else None


def _pd_diag_direction(node, frame):
    point = om.MPoint(*cmds.xform(node, query=True, worldSpace=True, translation=True))
    matrix = om.MMatrix(cmds.xform(frame, query=True, worldSpace=True, matrix=True))
    point = point * matrix.inverse()
    vector = (point.x, point.y, point.z)
    length = math.sqrt(sum(v*v for v in vector))
    return {"position": vector, "length": length,
            "unit": tuple(v/length for v in vector) if length > 1e-8 else (0.0, 0.0, 0.0)}


def diagnose_pose_driver():
    selected = cmds.ls(selection=True, long=True) or []
    selected_ids = set(cmds.ls(selected, uuid=True) or []) if selected else set()
    candidates, invalid = [], []
    for group in cmds.ls('*.rtkPoseDriverVersion', objectsOnly=True, long=True, recursive=True) or []:
        try:
            if cmds.getAttr(group+'.rtkPoseDriverVersion') != '1':
                continue
            state = json.loads(cmds.getAttr(group+'.rtkPoseDriverState'))
            candidates.append((group, state))
        except (ValueError, RuntimeError) as exc:
            invalid.append({"group": group, "error": str(exc)})
    matches = [(group, state) for group, state in candidates
               if selected_ids & (set(state['members']) | {state['joint']})]
    if len(matches) != 1:
        if len(candidates) == 1:
            matches = candidates
        else:
            print('Select the PoseDriver cone (or its source joint) and run again.')
            if invalid:
                print(json.dumps(invalid, indent=2))
            return None
    group, state = matches[0]
    cone, frame = _pd_diag_node(state['cone']), _pd_diag_node(state['frame'])
    joint, aim = _pd_diag_node(state['joint']), _pd_diag_node(state['aim'])
    live = _pd_diag_direction(cone, frame)
    report = {"maya": cmds.about(version=True),
              "evaluation_mode": cmds.evaluationManager(query=True, mode=True),
              "units": {"angle": cmds.currentUnit(query=True, angle=True),
                        "linear": cmds.currentUnit(query=True, linear=True)},
              "group": group, "joint": joint, "cone": cone,
              "joint_rotate": _pd_diag_get(joint+'.rotate'),
              "aim_local_translate": _pd_diag_get(aim+'.translate'),
              "aim_local_rotate": _pd_diag_get(aim+'.rotate'),
              "cone_offset": _pd_diag_get(cone+'.translate'),
              "live_geometry": live,
              "live_node_vector": _pd_diag_get(_pd_diag_node(state['live'])+'.output'),
              "normalize": _pd_diag_get(cone+'.normalize'),
              "raw_sum_before_trace": _pd_diag_get(cone+'.rawWeightSum'),
              "poses": []}
    total_expected = 0.0
    for pose in state['poses']:
        target = _pd_diag_node(pose['center'])
        center = _pd_diag_direction(target, frame)
        dot = max(-1.0, min(1.0, sum(a*b for a,b in zip(live['unit'],center['unit']))))
        valid = live['length'] > 1e-8 and center['length'] > 1e-8
        angle = math.degrees(math.acos(dot)) if valid else None
        edge = math.cos(math.radians(pose['radius']))
        t = max(0.0, min(1.0, (dot-edge)/(1.0-edge))) if valid else 0.0
        expected = t*t*(3-2*t)
        total_expected += expected
        raw_plug = cone+'.'+pose['attribute']+'Raw'
        output_plug = cone+'.'+pose['attribute']
        row = {"pose": pose['name'], "target": target, "target_geometry": center,
               "angle_degrees": angle, "falloff_degrees": pose['radius'],
               "expected_raw": expected, "actual_raw_before_trace": _pd_diag_get(raw_plug),
               "actual_weight_before_trace": _pd_diag_get(output_plug),
               "raw_source": _pd_diag_source(raw_plug),
               "weight_source": _pd_diag_source(output_plug)}
        ramp = _pd_diag_node(pose['ramp'])
        dot_source = _pd_diag_source(ramp+'.inputValue')
        cosine = dot_source.rsplit('.',1)[0] if dot_source else None
        row['ramp'] = {"input": _pd_diag_get(ramp+'.inputValue'),
                       "min": _pd_diag_get(ramp+'.inputMin'),
                       "max": _pd_diag_get(ramp+'.inputMax'),
                       "output": _pd_diag_get(ramp+'.outValue'),
                       "input_source": dot_source}
        if cosine:
            row['dot_node'] = {"type": cmds.nodeType(cosine),
                               "input1": _pd_diag_get(cosine+'.input1'),
                               "input2": _pd_diag_get(cosine+'.input2'),
                               "output": _pd_diag_get(cosine+'.outputX')}
        raw_source = row['raw_source']
        if raw_source:
            gate = raw_source.rsplit('.',1)[0]
            if cmds.nodeType(gate) == 'condition':
                row['zero_direction_gate'] = {
                    "length": _pd_diag_get(gate+'.firstTerm'),
                    "threshold": _pd_diag_get(gate+'.secondTerm'),
                    "true_weight": _pd_diag_get(gate+'.colorIfTrueR'),
                    "output": _pd_diag_get(gate+'.outColorR')}
        row['actual_raw_after_trace'] = _pd_diag_get(raw_plug)
        row['actual_weight_after_trace'] = _pd_diag_get(output_plug)
        report['poses'].append(row)
    report['expected_raw_sum'] = total_expected
    report['raw_sum_after_trace'] = _pd_diag_get(cone+'.rawWeightSum')
    normalize = report['normalize']
    for row in report['poses']:
        raw = row['expected_raw']
        row['expected_weight'] = (1-normalize)*raw + normalize*(raw/total_expected if total_expected else 0)
    print('POSEDRIVER DIAGNOSTIC BEGIN')
    print(json.dumps(report, indent=2))
    print('POSEDRIVER DIAGNOSTIC END')
    return report


if __name__ == '__main__':
    diagnose_pose_driver()
