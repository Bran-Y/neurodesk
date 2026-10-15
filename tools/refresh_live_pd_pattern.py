"""Recover generated widget output when the browser execution extension fails."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

import nbformat
from jupyter_client import BlockingKernelClient


def run(pid):
    target = Path('00_START_HERE.ipynb')
    previous = target.read_bytes()
    notebook = nbformat.reads(previous.decode(), as_version=4)
    cells = [c for c in notebook.cells if c.cell_type == 'code' and 'user_pipeline.show()' in c.source]
    assert len(cells) == 1, 'Ambiguous workflow entry'
    source = cells[0].source
    args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    assert 'ipykernel_launcher' in args and '-f' in args
    client = BlockingKernelClient(connection_file=args[args.index('-f') + 1])
    client.load_connection_file()
    client.start_channels()
    outputs = []

    def collect(message):
        kind, data = message['msg_type'], message['content']
        if kind == 'clear_output':
            outputs.clear()
        elif kind in ('display_data', 'execute_result'):
            outputs.append(nbformat.v4.new_output(kind, **data))
        elif kind in ('stream', 'error'):
            outputs.append(nbformat.v4.new_output(kind, **data))

    chunks = []
    try:
        client.wait_for_ready(timeout=15)
        reply = client.execute_interactive(source, timeout=90, store_history=False, allow_stdin=False, output_hook=collect)
        assert reply['content']['status'] == 'ok', 'Entry execution failed'
        assert any('application/vnd.jupyter.widget-view+json' in o.get('data', {}) for o in outputs), 'No live UI generated'

        def state_output(message):
            if message['msg_type'] == 'stream':
                chunks.append(message['content']['text'])

        result = client.execute_interactive(
            "import json; from ipywidgets import Widget; print(json.dumps(Widget.get_manager_state(drop_defaults=True)))",
            timeout=30, store_history=False, allow_stdin=False, output_hook=state_output)
        assert result['content']['status'] == 'ok'
        state = json.loads(''.join(chunks))
    finally:
        client.stop_channels()
    assert cells[0].source == source and target.read_bytes() == previous, 'Notebook changed during refresh'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('maintenance/pd_pattern_profile_20261007') / ('live_' + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(target, backup / target.name)
    cells[0].outputs = outputs
    cells[0].execution_count = reply['content']['execution_count']
    notebook.metadata['widgets'] = {'application/vnd.jupyter.widget-state+json': state}
    for cell in notebook.cells:
        if cell.cell_type == 'code' and cell is not cells[0] and (not cell.source.strip() or cell.source.lstrip().startswith('#')):
            cell.outputs = []
            cell.execution_count = None
    nbformat.validate(notebook)
    staged = target.with_name(target.name + '.widget-tmp')
    nbformat.write(notebook, staged)
    staged.replace(target)
    print('Restored generated live controls; source code unchanged. Widget models:', len(state['state']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel-pid', type=int, required=True)
    run(parser.parse_args().kernel_pid)
