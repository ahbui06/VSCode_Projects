from types import SimpleNamespace

import pytest

from electricity_ao.agents import OpenAIBackend
from electricity_ao.demo import demo_terms
from electricity_ao.models import ProviderConfig


def test_structured_api_call_and_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    backend = OpenAIBackend(model="gpt-5")
    calls = []
    expected = demo_terms("Example", 8)

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=expected)

    backend.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    provider = ProviderConfig(provider_id="example", company="Example", contract_path="unused.pdf")
    assert backend.extract(provider, ["Contract text"]) == expected
    assert calls[0]["model"] == "gpt-5"
    assert calls[0]["store"] is False
    assert "PAGE 1" in calls[0]["input"][1]["content"]
    expected = None
    with pytest.raises(ValueError, match="no validated output"):
        backend.extract(provider, ["Contract text"])
