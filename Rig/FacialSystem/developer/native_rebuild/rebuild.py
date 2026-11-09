"""Compile the scoped facial behavior to a self-contained Maya ASCII scene.

No Maya installation is needed to generate the file. Maya 2024 evaluates the
result using stock nodes and built-in expressions. No Python callbacks are used.
"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import math
import re

PREFIX = 'NFRv1_'


def quaternion_polynomials(order):
    """Symbolic local Euler-to-quaternion conversion in Maya's rotation order."""
    def add(*polys):
        result = collections.defaultdict(int)
        for polynomial, sign in polys:
            for term, factor in polynomial.items(): result[term] += sign * factor
        return {k: v for k, v in result.items() if v}
    def mul(a, b):
        result = collections.defaultdict(int)
        for x, u in a.items():
            for y, v in b.items(): result[tuple(sorted(x + y))] += u * v
        return {k: v for k, v in result.items() if v}
    def product(a, b):
        x, y, z, w = a; X, Y, Z, W = b
        return [add((mul(w, X), 1), (mul(x, W), 1), (mul(y, Z), 1), (mul(z, Y), -1)),
                add((mul(w, Y), 1), (mul(y, W), 1), (mul(z, X), 1), (mul(x, Z), -1)),
                add((mul(w, Z), 1), (mul(z, W), 1), (mul(x, Y), 1), (mul(y, X), -1)),
                add((mul(w, W), 1), (mul(x, X), -1), (mul(y, Y), -1), (mul(z, Z), -1))]
    axes = {}
    for i, axis in enumerate('xyz'):
        q = [{}, {}, {}, {}]
        q[i] = {('s' + axis,): 1}; q[3] = {('c' + axis,): 1}
        axes[axis] = q
    return product(axes[order[2]], product(axes[order[1]], axes[order[0]]))


def number(value):
    if not math.isfinite(value):
        raise ValueError('Non-finite coefficient')
    return format(float(value), '.17g')


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'


def statements(text):
    """Lexical MEL statement splitter respecting strings and both comment forms."""
    start, i, quoted, escaped = 0, 0, False, False
    line_comment, block_comment = False, False
    while i < len(text):
        char = text[i]
        if line_comment:
            if char == '\n': line_comment = False
        elif block_comment:
            if text[i:i + 2] == '*/': block_comment = False; i += 1
        elif quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif text[i:i + 2] == '//': line_comment = True; i += 1
        elif text[i:i + 2] == '/*': block_comment = True; i += 1
        elif char == '"': quoted = True
        elif char == ';':
            yield text[start:i + 1]
            start = i + 1
        i += 1
    if quoted or block_comment:
        raise ValueError('Unterminated Maya statement')
    if text[start:].strip(): yield text[start:]


def command(statement):
    clean = re.sub(r'(?m)^\s*//[^\n]*', '', statement).strip()
    match = re.match(r'(\w+)', clean)
    return match[1] if match else '', clean


def strip_dependencies(source, model):
    """Preserve native rig statements while replacing external evaluator/shaders."""
    created = list(re.finditer(r'^createNode\s+(\S+)[^;]*;', source, re.M))
    removed = set()
    shaders = set()
    for match in created:
        name = re.search(r'-n\s+"([^"]+)"', match[0])
        if not name: continue
        if match[1] in ['embeddedNodeRL4', 'dx11Shader', 'aiOptions', 'aiAOVDriver', 'aiAOVFilter', 'script']:
            removed.add(name[1])
            if match[1] == 'dx11Shader': shaders.add(name[1])
    if model['source_solver'] not in removed:
        raise ValueError('Reference evaluator missing from scene')
    output, skipped = [], collections.Counter()
    current_removed = False
    for original in statements(source):
        cmd, clean = command(original)
        if cmd == 'requires':
            if not re.match(r'requires\s+maya\s+', clean): skipped['requires'] += 1; continue
        if cmd == 'createNode':
            name = re.search(r'-n\s+"([^"]+)"', clean)
            current_removed = bool(name and name[1] in removed)
            if current_removed: skipped['nodes'] += 1; continue
        elif cmd == 'select':
            names = re.findall(r'"([^"]+)"', clean)
            current_removed = any(n.lstrip(':') in removed for n in names)
            if current_removed: continue
        if current_removed and cmd in ['setAttr', 'addAttr', 'rename']:
            continue
        if cmd in ['connectAttr', 'disconnectAttr']:
            plugs = re.findall(r'"([^"]+)"', clean)
            if any(p.split('.', 1)[0].lstrip(':') in removed for p in plugs):
                # Restore shader message/outColor connections onto native replacements.
                keep = (len(plugs) == 2 and plugs[0].split('.', 1)[0] in shaders and
                        plugs[0].split('.', 1)[1] in ['oc', 'outColor', 'msg', 'message'] and
                        plugs[1].split('.', 1)[0].lstrip(':') not in removed)
                if not keep: skipped['connections'] += 1; continue
        output.append(original)
    shader_nodes = []
    for name in sorted(shaders):
        color = [.62, .66, .71]
        if 'eye' in name.lower(): color = [.78, .80, .82]
        elif 'teeth' in name.lower(): color = [.77, .75, .69]
        shader_nodes.append('createNode lambert -n ' + quote(name) + ';\n' +
                            'setAttr ".color" -type "double3" ' + ' '.join(number(v) for v in color) + ';\n')
    # Replacements must exist before the preserved source connection section.
    text = ''.join(output)
    where = re.search(r'^connectAttr\s', text, re.M)
    position = where.start() if where else len(text)
    text = text[:position] + '\n' + ''.join(shader_nodes) + text[position:]
    return text, {'removed_nodes': sorted(removed), 'replaced_shaders': sorted(shaders), 'skipped': dict(skipped)}


class Compiler:
    def __init__(self, model):
        self.model = model
        self.nodes, self.links, self.expressions = [], [], []
        self.matrix_blocks = []
        self.node_types = collections.Counter()

    def node(self, kind, name, attrs=()):
        self.node_types[kind] += 1
        self.nodes.append('createNode ' + kind + ' -n ' + quote(name) + ';\n' + '\n'.join(attrs) + '\n')
        return name

    def link(self, source, destination):
        self.links.append('connectAttr ' + quote(source) + ' ' + quote(destination) + ';\n')

    def expression(self, name, lines):
        body = '\n'.join(lines)
        self.node_types['expression'] += 1
        self.expressions.append({'name': name, 'body': body})

    def signal(self, index):
        raw = self.model['raw_count']
        if index < raw: return f'{PREFIX}RAW.value[{index}]'
        if index < raw + self.model['psd_count']: return f'{PREFIX}PSD.value[{index - raw}]'
        return f'{PREFIX}RBF.value[{index - raw - self.model["psd_count"]}]'

    def buses(self):
        for name, count in [('RAW', self.model['raw_count']), ('PSD', self.model['psd_count']), ('RBF', self.model['rbf_count'])]:
            self.node('network', PREFIX + name, [
                'addAttr -ln "value" -at "double" -multi;',
                'setAttr -s ' + str(count) + ' ".value";'])
        for source in self.model['raw_sources']:
            self.link(source['source'], self.signal(source['index']))
        # The reference node accepts Euler driver channels but the DNA expects
        # local-rotation quaternions. A built-in expression performs conversion,
        # including all six Maya rotation orders, without matrix plug-ins.
        for joint in self.model['driver_joints']:
            lines = ['// Local Euler rotations are read in radians (unitConversion=none).']
            for axis in 'xyz':
                lines.append(f'float $s{axis} = sin({joint}.rotate{axis.upper()}*0.5);')
                lines.append(f'float $c{axis} = cos({joint}.rotate{axis.upper()}*0.5);')
            for index, order in enumerate(['xyz', 'yzx', 'zxy', 'xzy', 'yxz', 'zyx']):
                lines.append(('if' if index == 0 else 'else if') + f' ({joint}.rotateOrder == {index}) {{')
                for axis, polynomial in zip('xyzw', quaternion_polynomials(order)):
                    raw_index = self.model['raw_names'].index(joint + '.q' + axis)
                    terms = [f'({factor})*' + '*'.join('$' + name for name in term)
                             for term, factor in sorted(polynomial.items())]
                    lines.append(self.signal(raw_index) + ' = ' + ' + '.join(terms) + ';')
                lines.append('}')
            self.expression(PREFIX + joint + '_quaternion', lines)

    def rbf(self):
        for si, solver in enumerate(self.model['rbf_solvers']):
            # All values are local numeric variables, so this expression has no
            # getAttr/setAttr/eval calls, time dependency, or Python callbacks.
            lines = ['// Quaternion driver correction compiled from DNA.']
            source = [self.signal(i) for i in solver['input_indices']]
            lines.append('float $q[] = {' + ','.join(source) + '};')
            kernels = []
            for ti, target in enumerate(solver['targets']):
                lines.append('float $distance2_' + str(ti) + ' = 0.0;')
                for qi in range(0, len(target), 4):
                    var = f'{ti}_{qi // 4}'
                    dot = ' + '.join(f'$q[{qi + k}]*({number(target[qi + k])})' for k in range(4))
                    lines += [f'float $dot_{var} = {dot};', f'float $dot2_{var} = $dot_{var}*$dot_{var};',
                              f'float $arc_{var} = 0.0;',
                              f'if ($dot2_{var} <= 1.0) $arc_{var} = acos(clamp(-1.0,1.0,2.0*$dot2_{var}-1.0));',
                              f'$distance2_{ti} = $distance2_{ti} + $arc_{var}*$arc_{var};']
                radius2 = number(solver['radius'] ** 2)
                lines.append(f'float $kernel_{ti} = exp(-sqrt($distance2_{ti})/({radius2}));')
                kernels.append(f'$kernel_{ti}')
            weights = []
            for wi, coeff in enumerate(solver['coefficients']):
                terms = ' + '.join(f'({number(c)})*{k}' for c, k in zip(coeff, kernels) if c != 0)
                lines.append(f'float $weight_{wi} = clamp(0.0,1.0,{terms or "0.0"});')
                weights.append(f'$weight_{wi}')
            lines.append('float $total = ' + ' + '.join(weights) + ';')
            lines.append('float $ratio = 1.0;')
            condition = '$total > 1.0' if solver['normalize_method'] == 0 else '$total > 0.0'
            lines.append(f'if ({condition}) $ratio = 1.0/$total;')
            contributions = collections.defaultdict(list)
            for i, pose in enumerate(solver['poses']):
                v = f'$weight_{i}'
                lines.append(f'{v} = {v}*$ratio*({number(pose["scale"])});')
                lines.append(f'if ({v} <= {number(solver["threshold"])}) {v} = 0.0;')
                gating = ''.join('*(' + self.signal(c) + ')' for c in pose['inputControlIndices'])
                for out, factor in zip(pose['outputControlIndices'], pose['outputControlWeights']):
                    contributions[out].append(f'({number(factor)})*{v}{gating}')
            for out, terms in sorted(contributions.items()):
                lines.append(self.signal(out) + ' = ' + ' + '.join(terms) + ';')
            self.expression(PREFIX + 'neck_rbf_' + str(si), lines)

    def psds(self):
        for start in range(0, len(self.model['psds']), 40):
            lines = ['// Product corrective controls; clamp inputs before multiplication.']
            for psd in self.model['psds'][start:start + 40]:
                factors = [number(psd['weight'])] + [f'clamp(0.0,1.0,{self.signal(i)})' for i in psd['inputs']]
                lines.append(self.signal(psd['output']) + ' = min(1.0,' + '*'.join(factors) + ');')
            self.expression(PREFIX + 'correctives_' + str(start // 40).zfill(2), lines)

    def matrices(self):
        outputs = self.model['outputs']
        for start in range(0, len(outputs), 9):
            group = outputs[start:start + 9]
            name = PREFIX + 'joint_matrix_' + str(start // 9).zfill(3)
            mats = collections.defaultdict(lambda: [0.0] * 16)
            for slot, output in enumerate(group):
                cell = (slot // 3) * 4 + slot % 3
                mats[-1][cell] = output['neutral']
                for signal, weight in output['terms']:
                    mats[signal][cell] = weight
            attrs = []
            entries = []
            for i, (signal, mat) in enumerate(sorted(mats.items())):
                attrs.append(f'setAttr ".wtMatrix[{i}].matrixIn" -type "matrix" ' + ' '.join(number(v) for v in mat) + ';')
                attrs.append(f'setAttr ".wtMatrix[{i}].weightIn" ' + ('1;' if signal < 0 else '0;'))
                if signal >= 0: self.link(self.signal(signal), f'{name}.wtMatrix[{i}].weightIn')
                entries.append({'slot': i, 'signal': signal})
            self.node('wtAddMatrix', name, attrs)
            for row in range((len(group) + 2) // 3):
                extractor = self.node('pointMatrixMult', name + '_row' + str(row), [
                    'setAttr ".vectorMultiply" yes;',
                    'setAttr ".inPoint" -type "double3" ' + ' '.join('1' if i == row else '0' for i in range(3)) + ';'])
                self.link(name + '.matrixSum', extractor + '.inMatrix')
                for col in range(3):
                    slot = row * 3 + col
                    if slot >= len(group): continue
                    output = group[slot]
                    conversion = self.node('unitConversion', PREFIX + 'channel_' + str(start + slot).zfill(4), [
                        'setAttr ".conversionFactor" ' + number(math.pi / 180 if 3 <= output['dof'] < 6 else 1) + ';'])
                    self.link(extractor + '.output' + 'XYZ'[col], conversion + '.input')
                    self.link(conversion + '.output', output['destination'])
            self.matrix_blocks.append({'name': name, 'output_start': start, 'output_count': len(group), 'entries': entries})

    def maps(self):
        table = self.model['animated_maps']
        # Keep consecutive intervals for one input/output as first-match chains.
        groups = []
        row = 0
        while row < len(table['inputIndices']):
            i, o = table['inputIndices'][row], table['outputIndices'][row]
            end = row + 1
            while end < len(table['inputIndices']) and table['inputIndices'][end] == i and table['outputIndices'][end] == o:
                end += 1
            groups.append((i, o, list(range(row, end))))
            row = end
        for offset in range(0, len(self.model['animated_map_links']), 24):
            links = self.model['animated_map_links'][offset:offset + 24]
            lines = ['// Animated material multipliers preserved as numeric outputs.']
            for link in links:
                var = '$m' + str(link['index'])
                lines.append(f'float {var} = 0.0;')
                for index, out, rows in groups:
                    if out != link['index']: continue
                    signal = self.signal(index)
                    for j, r in enumerate(rows):
                        condition = f'({signal} >= {number(table["fromValues"][r])} && {signal} <= {number(table["toValues"][r])})'
                        calc = f'({number(table["slopeValues"][r])})*{signal}+({number(table["cutValues"][r])})'
                        lines.append(('if ' if j == 0 else 'else if ') + condition + f' {var} = {var}+({calc});')
                lines.append(link['destination'] + f' = clamp(0.0,1.0,{var});')
            self.expression(PREFIX + 'animated_maps_' + str(offset // 24), lines)

    def compile(self):
        self.buses(); self.rbf(); self.psds(); self.matrices(); self.maps()
        return self


def build_scene(source_path, model, output_dir):
    source_path, output_dir = Path(source_path), Path(output_dir)
    data = source_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != model['source_scene_sha256']:
        raise ValueError('This behavior map belongs to a different source scene')
    source = data.decode('cp1252')
    if re.search(r'createNode[^;]* -n "' + PREFIX, source):
        raise ValueError('Scene already contains this reconstruction')
    source, stripped = strip_dependencies(source, model)
    compiler = Compiler(model).compile()
    output_dir.mkdir(parents=True, exist_ok=True)
    expression_dir = output_dir / 'expressions'
    expression_dir.mkdir(exist_ok=True)
    compiled = []
    for expression in compiler.expressions:
        (expression_dir / (expression['name'] + '.mel')).write_text(expression['body'], encoding='utf-8')
        compiled.append('expression -name ' + quote(expression['name']) +
                        ' -alwaysEvaluate 0 -unitConversion "none" -string ' + quote(expression['body']) + ';\n')
    # Maya loads all graph objects before resolving the compiler's links and
    # built-in expression commands. Native materials were inserted above their
    # original shading connections by strip_dependencies.
    result = source + '\n// Native facial reconstruction: no external evaluator.\n' + ''.join(compiler.nodes)
    result += ''.join(compiler.links) + ''.join(compiled)
    result += '\nplaybackOptions -min 0 -max 30 -ast 0 -aet 30;\n'
    destination = output_dir / 'facialRig_native_v1.ma'
    destination.write_text(result, encoding='cp1252')
    report = {'source_scene': source_path.name, 'output_scene': destination.name,
              'scope_joint_count': model['scope_joint_count'], 'connected_joint_channels': len(model['outputs']),
              'expression_inputs': len(model['raw_sources']), 'driver_joints': model['driver_joints'],
              'generated_node_types': dict(compiler.node_types), 'matrix_blocks': compiler.matrix_blocks,
              'dependencies': stripped, 'runtime_external_plugins': [], 'maya_runtime_tested': False}
    (output_dir / 'build_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return destination, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('scene')
    p.add_argument('--behavior', default=str(Path(__file__).resolve().parents[2] / 'facial_system' / 'data' / 'behavior.json'))
    p.add_argument('--output', default=str(Path(__file__).parent / 'rebuilt'))
    args = p.parse_args()
    path, report = build_scene(args.scene, json.loads(Path(args.behavior).read_text()), args.output)
    print(json.dumps({'scene': str(path), 'joints': report['scope_joint_count'],
                      'generated_nodes': report['generated_node_types']}, indent=2))


if __name__ == '__main__': main()
