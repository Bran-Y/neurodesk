"""Transient password input: custom messages, never synchronized secret traits."""
import os

import anywidget

from ai_evidence_assistant import KEY_ENV


class KernelKeyInput(anywidget.AnyWidget):
    # The password stays in the DOM until submission, then goes only to the kernel.
    # Never use model.set/save_changes for this value: widget state is exportable.
    _esm = """
    function render({ model, el }) {
      const title = document.createElement('h4');
      title.textContent = 'AI connection';
      const note = document.createElement('p');
      note.textContent = 'Key stays in this kernel only. This does not call the AI service or send patient data.';
      const status = document.createElement('p');
      status.setAttribute('role', 'status');
      status.textContent = 'Checking current kernel...';
      const field = document.createElement('input');
      field.type = 'password';
      field.autocomplete = 'off';
      field.spellcheck = false;
      field.maxLength = 4096;
      field.setAttribute('aria-label', 'API key (kernel memory only)');
      field.placeholder = 'API key';
      field.style.width = 'min(420px, 95%)';
      const save = document.createElement('button');
      save.textContent = 'Use key in this kernel';
      const clear = document.createElement('button');
      clear.textContent = 'Clear key';
      const replace = document.createElement('button');
      replace.textContent = 'Replace key';
      const form = document.createElement('div');
      form.append(field, save);
      const buttons = [save, clear, replace];
      for (const button of buttons) {
        button.type = 'button';
        button.className = 'jupyter-button widget-button';
        button.style.margin = '4px';
        button.style.width = 'auto';
        button.disabled = true;
      }
      field.disabled = true;
      const pending = () => {
        buttons.forEach(button => button.disabled = true);
        field.disabled = true;
        status.textContent = 'Waiting for the kernel...';
      };
      const submit = () => {
        if (save.disabled) return;
        let key = field.value.trim();
        field.value = '';
        if (!key || /\\s/.test(key)) {
          status.textContent = 'Enter a non-empty key without whitespace.';
          return;
        }
        pending();
        model.send({ action: 'configure', key });
        key = '';
      };
      const onKey = event => {
        if (event.key === 'Enter') { event.preventDefault(); submit(); }
      };
      const onClear = () => {
        field.value = '';
        pending();
        model.send({ action: 'clear' });
      };
      const onReplace = () => { form.hidden = false; field.focus(); };
      const onMessage = message => {
        if (message.type !== 'key-status') return;
        field.value = '';
        field.disabled = false;
        buttons.forEach(button => button.disabled = false);
        clear.disabled = replace.disabled = !message.configured;
        form.hidden = message.configured && !message.error;
        status.textContent = message.error || (message.configured
          ? 'API key configured in this kernel. Ready for Generate AI report. No request sent.'
          : 'No key in this kernel. Configure once; reconfigure after a kernel restart.');
      };
      save.addEventListener('click', submit);
      field.addEventListener('keydown', onKey);
      clear.addEventListener('click', onClear);
      replace.addEventListener('click', onReplace);
      model.on('msg:custom', onMessage);
      el.append(title, note, status, form, replace, clear);
      model.send({ action: 'status' });
      return () => {
        field.value = '';
        model.off('msg:custom', onMessage);
        save.removeEventListener('click', submit);
        field.removeEventListener('keydown', onKey);
        clear.removeEventListener('click', onClear);
        replace.removeEventListener('click', onReplace);
      };
    }
    export default { render };
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.on_msg(self._receive)

    def _receive(self, widget, content, buffers):
        if not isinstance(content, dict):
            return
        action = content.get('action')
        key = content.pop('key', None)
        error = None
        if action == 'configure':
            if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(c.isspace() for c in key):
                error = 'Invalid key. Enter a non-empty key without whitespace.'
            else:
                os.environ[KEY_ENV] = key
        elif action == 'clear':
            os.environ.pop(KEY_ENV, None)
        elif action != 'status':
            return
        key = None
        self.send(dict(type='key-status', configured=bool(os.environ.get(KEY_ENV)), error=error))


def show_api_key_setup():
    """Return a password input without reading or exposing the current key."""
    return KernelKeyInput()
