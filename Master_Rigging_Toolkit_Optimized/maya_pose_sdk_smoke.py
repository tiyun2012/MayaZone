"""Native SDK/weighted-curve mirror fixture. Run inside Maya after toolkit reload.

No scene replacement or Undo reset; only a unique namespace and captured SDK
records are cleaned. Maya was unavailable on the package build host.
"""
import math
import uuid
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import master_rigging_toolkit as toolkit


def run():
    api=toolkit._pd_sdk_module('pose_driver_sdk')
    prefix='rtkSDKSmoke_'+uuid.uuid4().hex[:8];previous=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or [];metas=set();checks=[]
    def sample(curve,x):
        s=om.MSelectionList();s.add(curve);return oma.MFnAnimCurve(s.getDependNode(0)).evaluate(float(x))
    def native_value(channel,v):return api.convert(channel,v,api.units(),{'angle':'rad','linear':'cm'})
    def close(a,b):return abs(a-b)<=2e-5*max(1.,abs(a),abs(b))
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        left=cmds.createNode('transform',name=prefix+':SDK_L',skipSelect=True)
        right=cmds.createNode('transform',name=prefix+':SDK_R',skipSelect=True)
        a=cmds.createNode('network',name=prefix+':weights_L',skipSelect=True)
        b=cmds.createNode('network',name=prefix+':weights_R',skipSelect=True)
        for n in (a,b):cmds.addAttr(n,longName='weight',attributeType='double',minValue=0,maxValue=1,defaultValue=0,keyable=True)
        wa,wb=a+'.weight',b+'.weight'
        deg=lambda v:api.convert('rotateY',v,{'angle':'deg','linear':'cm'},api.units())
        cm=lambda v:api.convert('translateX',v,{'angle':'deg','linear':'cm'},api.units())
        cmds.setAttr(left+'.translateX',cm(2));cmds.setAttr(left+'.rotateY',deg(10))
        cmds.setAttr(right+'.translateZ',cm(-7));cmds.setAttr(right+'.rotateZ',deg(-12));cmds.setAttr(right+'.scaleX',.7)
        rows=api.inspect(wa,left)['rows']
        for row in rows:
            c=row['channel'];row['enabled']=c in ('translateX','rotateY','scaleZ')
            if c=='translateX':row.update(value=cm(8),mirror_channel='translateZ',target_neutral=cm(-7),rule='flip_delta')
            elif c=='rotateY':row.update(value=deg(40),mirror_channel='rotateZ',target_neutral=deg(-12),rule='flip_delta')
            elif c=='scaleZ':row.update(value=1.6,mirror_channel='scaleX',target_neutral=.7,rule='keep_delta',input_rule='reverse')
        result=api.capture(wa,left,rows,1);metas.add(api.identity(result['meta']))
        for row in rows:
            if not row['enabled']:continue
            row['value']=row['neutral']+.65*(row['value']-row['neutral'])
        api.capture(wa,left,rows,.4);checks.append('typed TRS SDK capture')
        enabled=[r for r in rows if r['enabled']]
        for row in enabled:
            curve=api.direct_curve(left+'.'+row['channel'])
            cmds.keyTangent(curve,edit=True,weightedTangents=True)
            cmds.keyTangent(curve,edit=True,index=(0,2),inTangentType='auto',outTangentType='auto')
            cmds.setInfinity(curve,preInfinite='linear',postInfinite='constant')
        before=cmds.ls(type='animCurve') or []
        api.preview_mirror(wa,left,wb,right,rows);assert (cmds.ls(type='animCurve') or [])==before
        result=api.mirror(wa,left,wb,right,rows);metas.add(api.identity(result['meta']))
        for row in enabled:
            src=api.direct_curve(left+'.'+row['channel']);dst=api.direct_curve(right+'.'+row['mirror_channel'])
            assert cmds.getAttr(src+'.weightedTangents')==cmds.getAttr(dst+'.weightedTangents')
            for i in range(45):
                x=-.1+i*1.2/44;u=1.-x if row['input_rule']=='reverse' else x
                value=sample(src,u);base=native_value(row['channel'],row['neutral']);target=native_value(row['mirror_channel'],row['target_neutral'])
                expected=target+(-1 if row['rule']=='flip_delta' else 1)*(value-base)
                assert close(sample(dst,x),expected),(row['channel'],x,sample(dst,x),expected)
        checks.append('weighted curves, neutral/sign/axis mirror and reversed infinity')
        cmds.undo();assert api.direct_curve(right+'.translateZ') is None
        cmds.redo();assert api.direct_curve(right+'.translateZ') is not None;checks.append('native mirror Undo/Redo')
        # Conservative cycle protection: a target contributes to its own driver.
        cycle=cmds.createNode('network',name=prefix+':cycleWeight',skipSelect=True)
        cmds.addAttr(cycle,longName='weight',attributeType='double');cmds.connectAttr(right+'.translateY',cycle+'.weight')
        try:api.capture(cycle+'.weight',right,api.inspect(cycle+'.weight',right)['rows'],1)
        except ValueError as exc:assert 'cycle' in str(exc).lower()
        else:raise AssertionError('Upstream driven transform was accepted')
        checks.append('native dependency traversal')
        cmds.setAttr(wa,.6);cmds.setAttr(wb,.6)
        poses={(n,r['channel'] if n==left else r['mirror_channel']):cmds.getAttr(n+'.'+(r['channel'] if n==left else r['mirror_channel'])) for n in (left,right) for r in enabled}
        for ref in list(metas):
            try:meta=api.resolve(ref)
            except ValueError:continue
            api.remove(meta)
        for (n,c),v in poses.items():assert close(cmds.getAttr(n+'.'+c),v)
        checks.append('SDK removal preserves posed values')
        report={'passed':len(checks),'checks':checks,'scene_units':api.units()};print('Pose SDK native smoke:',report);return report
    finally:
        # Only nodes recorded by this fixture can be deleted outside its namespace.
        for ref in metas:
            try:meta,data=api.read(api.resolve(ref))
            except (ValueError,RuntimeError):continue
            owned=[]
            for row in data['rows'].values():
                if row.get('curve'):
                    try:owned.append(api.resolve(row['curve']))
                    except ValueError:pass
            if owned:cmds.delete(owned)
            if cmds.objExists(meta):cmds.delete(meta)
        nodes=cmds.ls(prefix+':*',long=True) or []
        if nodes:cmds.delete(nodes)
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=previous)
        cmds.select([n for n in selection if cmds.objExists(n)],replace=True) if selection else cmds.select(clear=True)
