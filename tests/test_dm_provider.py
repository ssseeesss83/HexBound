"""Provider reasoning options are explicit and never consume live credentials."""
import asyncio
import json
import httpx
import pytest
from backend.dm import DM


@pytest.mark.parametrize('effort',[None,'none','low','high','max'])
def test_optional_reasoning_preserves_default_and_caps_requested_output(monkeypatch,effort):
    monkeypatch.setenv('LLM_API_KEY','test-credential')
    monkeypatch.setenv('LLM_MODEL','test-model')
    monkeypatch.setenv('LLM_BASE_URL','https://provider.invalid/v1/')
    if effort is None:monkeypatch.delenv('LLM_REASONING_EFFORT',raising=False)
    else:monkeypatch.setenv('LLM_REASONING_EFFORT',effort)
    seen=[]
    def respond(request):
        assert str(request.url)=='https://provider.invalid/v1/chat/completions'
        body=json.loads(request.content)
        assert body['max_tokens']==48 and body['response_format']==dict(type='json_object')
        assert (body.get('reasoning_effort')==effort)
        assert ('reasoning_effort' in body)==(effort is not None)
        seen.append(body)
        return httpx.Response(200,json=dict(choices=[dict(message=dict(content=' {"ok": true} '))]))
    client_type=httpx.AsyncClient
    monkeypatch.setattr('backend.dm.httpx.AsyncClient',lambda **kwargs:client_type(transport=httpx.MockTransport(respond),**kwargs))
    result=asyncio.run(DM()._complete('Return JSON.',{'fixture':True},True,max_tokens=48))
    assert json.loads(result)==dict(ok=True) and len(seen)==1


def test_invalid_reasoning_configuration_fails_before_any_provider_call(monkeypatch):
    monkeypatch.setenv('LLM_REASONING_EFFORT','unbounded')
    with pytest.raises(ValueError,match='LLM_REASONING_EFFORT'):DM()
