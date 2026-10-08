"""Atomic case requests and an explicit live-kernel handshake for notebook controls."""
from pathlib import Path

import anywidget
import traitlets


class CaseControls(anywidget.AnyWidget):
    config = traitlets.Unicode('config.json').tag(sync=True)
    cases = traitlets.List(traitlets.Unicode()).tag(sync=True)
    _esm = Path(__file__).with_suffix('.js')

    def __init__(self, action, root, **kwargs):
        super().__init__(**kwargs)
        self.action = action
        self.active = True
        self._seen = set()
        self.cases = [str(p.relative_to(root)) for p in sorted(Path(root).glob('cases/*/config.json'))]
        self.on_msg(self.receive)

    def receive(self, widget, message, buffers):
        request_id = message.get('id')
        if not isinstance(request_id, str) or not self.active:
            return
        if message.get('type') == 'ping':
            self.send(dict(type='ready', id=request_id))
            return
        if message.get('type') != 'action' or request_id in self._seen:
            return
        self._seen.add(request_id)
        try:
            action = message.get('action')
            path = message.get('config')
            reference = message.get('reference')
            if action not in ('status', 'process', 'report'):
                raise ValueError('Unknown action')
            if not isinstance(path, str) or not path.strip():
                raise ValueError('Select a case configuration first')
            if reference not in ('config', 'PD', 'all'):
                raise ValueError('Unknown reference selection')
            consent = message.get('consent') is True
            if action == 'process' and not consent:
                raise ValueError('Explicit processing confirmation required')
            self.send(dict(type='accepted', id=request_id, config=path))
            result = self.action(path, reference, consent, action)
            self.send(dict(type='done', id=request_id, config=path,
                           ok=result.get('ok', False), error=result.get('error', '')))
        except Exception as exc:
            self.send(dict(type='done', id=request_id, ok=False,
                           error=type(exc).__name__ + ': ' + str(exc)))

    def close(self):
        self.active = False
        super().close()
