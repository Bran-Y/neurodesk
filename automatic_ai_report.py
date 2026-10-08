"""Automatic, cached AI drafts for the selected subject; never a diagnosis."""
import asyncio
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import tempfile
import time

import ai_evidence_assistant as ai


def policy(root):
    path = Path(root) / 'ai_report_policy.json'
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return (data.get('auto_generate') is True
            and data.get('authorised_endpoint') == ai.DEFAULTS['base_url']
            and bool(data.get('authorisation_basis'))
            and data.get('scope') == 'selected_subject_only_no_background_batch'
            and data.get('send_raw_images') is False
            and data.get('send_subject_identifiers') is False
            and data.get('automatic_retry') is False)


def _write_private(path, data):
    fd, name = tempfile.mkstemp(prefix='.ai-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=True, allow_nan=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class ReportCache:
    def __init__(self, root, config):
        self.root, self.config = Path(root), config
        self.directory = self.root / 'outputs' / '.ai_report_cache'

    def path(self, subject_id, payload):
        identity = dict(subject_id=subject_id, payload=ai.payload_hash(payload),
                        model=self.config['model'], endpoint=self.config['base_url'],
                        prompt=ai.PROMPT_VERSION, max_tokens=self.config['max_tokens'])
        key = hashlib.sha256(ai.serialise(identity).encode()).hexdigest()
        return self.directory / (key + '.json')

    def read(self, path, subject_id, payload):
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if data.get('local_subject_id') != subject_id or data.get('payload_sha256') != ai.payload_hash(payload):
                raise ai.AIError('Cached subject or evidence differs; no cached report accepted.')
            if data.get('status') == 'complete':
                audit = data['response']['audit']
                if (audit.get('requested_model') != self.config['model']
                        or audit.get('returned_model') != self.config['model']
                        or audit.get('base_url') != self.config['base_url']
                        or audit.get('prompt_version') != ai.PROMPT_VERSION
                        or audit.get('payload_sha256') != ai.payload_hash(payload)):
                    raise ai.AIError('Cached provenance differs; no cached report accepted.')
                ai.validate_answer(data['response']['answer'], payload)
            if data.get('status') not in ('complete', 'pending', 'failed'):
                raise ai.AIError('Unrecognised cached request status.')
            return data
        except (ValueError, KeyError, OSError, TypeError, AttributeError) as exc:
            if isinstance(exc, ai.AIError):
                raise
            raise ai.AIError('Stored AI request is unreadable. No automatic resubmission.') from None

    def generate(self, subject_id, payload):
        if not policy(self.root):
            raise ai.AIError('Automatic AI transmission is not authorised for this workflow.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        path = self.path(subject_id, payload)
        cached = self.read(path, subject_id, payload)
        if cached is not None:
            if cached['status'] == 'complete':
                self.save_html(path, cached['response'], payload)
            return cached
        from ai_credentials import load_api_key
        if not load_api_key():
            raise ai.AIError('Private .env is not configured; no request sent.')
        record = dict(status='pending', local_subject_id=subject_id,
            payload_sha256=ai.payload_hash(payload), prompt_version=ai.PROMPT_VERSION,
            started_at=datetime.now(timezone.utc).isoformat())
        # Claim before network I/O; reopening a notebook cannot duplicate a billed request.
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return self.read(path, subject_id, payload)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream)
        started = time.monotonic()
        try:
            response = ai.explain(payload, consent=True, config=self.config)
            self.save_html(path, response, payload)
            record.update(status='complete', response=response, evidence_payload=payload,
                          completed_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            message = str(exc) if isinstance(exc, ai.AIError) else 'AI generation failed; no report accepted.'
            record.update(status='failed', error=message,
                          completed_at=datetime.now(timezone.utc).isoformat())
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        _write_private(path, record)
        return record

    def save_html(self, path, response, payload):
        """Refresh presentation fixes without changing the audit or calling the model."""
        report = ai.render_explanation(response, payload)
        fd, name = tempfile.mkstemp(prefix='.ai-html-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write('<!doctype html><meta charset="utf-8">' + report)
            os.replace(name, path.with_suffix('.html'))
        finally:
            Path(name).unlink(missing_ok=True)


class AutomaticAIPanel:
    def __init__(self, result, subject_widget):
        import ipywidgets as w
        self.result, self.subject = result, subject_widget
        self.root = Path(result.get('project_dir', Path(__file__).parent))
        self.config = ai.settings(self.root)
        self.cache = ReportCache(self.root, self.config)
        self.output = w.HTML()
        self.response = self.payload = self.prepared_subject = None
        self.generation = 0
        self._tasks = set()
        self.closed = False
        note = w.HTML('<details><summary>AI processing and privacy</summary><p>'
            'Automatic research drafts are enabled for the selected subject, as requested. '
            'De-identified measurements and literature evidence go to llm.chudian.site '
            'using glm-5.3-flash; no subject ID, known diagnosis or MRI is sent. '
            'Third-party retention is unverified. Results are saved privately and reused. '
            'Set auto_generate to false in ai_report_policy.json to stop new requests. '
            'Failed or uncertain requests are not automatically retried.</p></details>')
        self.box = w.VBox([self.output, note])

    def current(self, generation, subject_id):
        return not self.closed and generation == self.generation and self.subject.value == subject_id

    def start(self):
        if self.closed:
            return
        self.generation += 1
        generation, subject_id = self.generation, self.subject.value
        self.response = self.payload = self.prepared_subject = None
        if not policy(self.root):
            self.output.value = '<p>Automatic AI reporting is disabled. No new request sent.</p>'
            return
        self.output.value = '<p>Preparing the AI assessment for ' + html.escape(subject_id) + '...</p>'
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.output.value = '<p>Live notebook event loop unavailable. No AI request started.</p>'
            return
        task = loop.create_task(self._run(generation, subject_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, generation, subject_id):
        try:
            # Ignore transient selections before committing to a paid request.
            await asyncio.sleep(0.4)
            if not self.current(generation, subject_id):
                return
            payload = ai.build_payload(self.result, subject_id)
            self.output.value = '<p>AI assessment is running in the background; the report will appear here automatically.</p>'
            record = await asyncio.wait_for(
                asyncio.to_thread(self.cache.generate, subject_id, payload),
                timeout=self.config['timeout_seconds'] + 20)
            # A different panel/kernel may already own the request. Poll cache, not API.
            elapsed = 0
            while record['status'] == 'pending' and elapsed < self.config['timeout_seconds'] + 20:
                if not self.current(generation, subject_id):
                    return
                await asyncio.sleep(2)
                elapsed += 2
                record = self.cache.read(self.cache.path(subject_id, payload), subject_id, payload)
            if not self.current(generation, subject_id):
                return
            if record['status'] == 'complete':
                self.payload, self.response, self.prepared_subject = payload, record['response'], subject_id
                self.output.value = ('<p><b>Patient:</b> ' + html.escape(subject_id) + '</p>' +
                    ai.render_explanation(self.response, payload) +
                    '<p><small>AI draft and evidence audit saved automatically. Unchanged inputs reuse this result.</small></p>')
                if 'output_dir' in self.result:
                    from report_quality import export_ai_snapshot, saved_report_link
                    try:
                        saved = export_ai_snapshot(self.result, subject_id, payload, self.response)
                        self.output.value += saved_report_link(saved, subject_id, 'AI research')
                    except (OSError, ValueError):
                        self.output.value += '<p>Standalone AI snapshot could not be saved. The cached audit is retained.</p>'
            elif record['status'] == 'failed':
                self.output.value = '<p>AI assessment unavailable: ' + html.escape(record['error']) + '</p>'
            else:
                self.output.value = '<p>An earlier AI request is pending or its outcome is unknown. No duplicate request sent.</p>'
        except TimeoutError:
            if self.current(generation, subject_id):
                self.output.value = '<p>AI is taking longer than expected. Request state is retained; no automatic retry.</p>'
        except Exception as exc:
            if self.current(generation, subject_id):
                message = str(exc) if isinstance(exc, ai.AIError) else 'AI report unavailable; numeric results are unchanged.'
                self.output.value = '<p>' + html.escape(message) + '</p>'

    def close(self):
        self.closed = True
        self.generation += 1
