"""Publish complete color handoffs through existing Maya viewport widgets.

No overlay, renderer override, global refresh suspension or Maya Undo commands.
Each widget's existing update state is restored, even after an operation fails.
"""
import contextlib

try:
    from PySide6 import QtWidgets
    import shiboken6 as shiboken
except ImportError:
    try:
        from PySide2 import QtWidgets
        import shiboken2 as shiboken
    except ImportError:QtWidgets=None;shiboken=None


def valid(widget):
    if shiboken is None:return False
    try:return shiboken.isValid(widget)
    except (TypeError,RuntimeError):return False


def surfaces(api):
    factory=getattr(api,'feedback_surfaces',None)
    if factory is not None:return factory()
    if QtWidgets is None or QtWidgets.QApplication.instance() is None:return []
    try:import maya.api.OpenMayaUI as omui
    except ImportError:return []  # Headless recording adapters have no Maya UI.
    result=[]
    for index in range(omui.M3dView.numberOf3dViews()):
        view=omui.M3dView.get3dView(index)
        if not view.isVisible():continue
        pointer=int(view.widget())
        if not pointer:continue
        widget=shiboken.wrapInstance(pointer,QtWidgets.QWidget)
        if valid(widget):result.append((widget,lambda view=view:view.refresh(False,True)))
    return result


class DisplayGate:
    def __init__(self,provider,on_error=None):
        self.provider=provider;self.on_error=on_error;self.depth=0
        self.handoffs=0;self.last_surfaces=0;self.last_error=None
        self.abandoned=False

    @contextlib.contextmanager
    def hold(self):
        if self.abandoned:
            yield;return
        if self.depth:
            self.depth+=1
            try:yield
            finally:self.depth-=1
            return
        self.depth=1;records=[];seen=set();errors=[]
        try:
            for widget,present in self.provider():
                if self.abandoned:break
                if not valid(widget):continue
                identity=int(shiboken.getCppPointer(widget)[0])
                if identity in seen:continue
                seen.add(identity)
                if not widget.updatesEnabled():continue
                records.append((widget,present))
                widget.setUpdatesEnabled(False)
            yield
        finally:
            try:
                # Restore every panel before presenting any one of them. Keep
                # depth nonzero during repaint callbacks to guard reentry.
                for widget,present in reversed(records):
                    if self.abandoned:break
                    if valid(widget):
                        try:widget.setUpdatesEnabled(True)
                        except RuntimeError as exc:errors.append(str(exc))
                for widget,present in records:
                    if self.abandoned:break
                    if valid(widget) and widget.updatesEnabled():
                        try:present()
                        except RuntimeError as exc:errors.append(str(exc))
            finally:
                self.depth=0;self.handoffs+=1;self.last_surfaces=len(records)
                self.last_error='; '.join(errors) if errors else None
                if errors and self.on_error and not self.abandoned:
                    try:self.on_error('Layer Skin color handoff: '+self.last_error)
                    except Exception:pass

    def report(self):
        return dict(active=bool(self.depth),handoffs=self.handoffs,surfaces=self.last_surfaces,
                    backend='batched native viewport updates',last_error=self.last_error,abandoned=self.abandoned)

    def abandon(self):
        # Maya owns late shutdown. Do not restore widgets or invoke view API
        # callbacks after kMayaExiting, even if an action was unwinding.
        self.abandoned=True
