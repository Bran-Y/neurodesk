"""Explicit one-request smoke test. Sends fabricated data only; no files or patients."""
import json
from ai_evidence_assistant import configure_api_key, clear_api_key, explain, AIError
from test_ai_evidence_assistant import synthetic_payload


if __name__ == '__main__':
    configure_api_key()
    try:
        response = explain(synthetic_payload(), consent=True)
        print(json.dumps(response, indent=2))
    except AIError as exc:
        print('Smoke test failed:', str(exc))
        raise SystemExit(1)
    finally:
        clear_api_key()
