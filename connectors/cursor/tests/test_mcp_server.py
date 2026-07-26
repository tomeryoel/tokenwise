import json

from connectors.cursor import mcp_server


def test_mcp_recommend_tool():
    response = mcp_server._handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "momihelm_recommend_model",
                "arguments": {
                    "objective": "Fix a flaky auth unit test",
                    "workflow": "agent",
                    "policy_mode": "balanced",
                },
            },
        }
    )
    assert response is not None
    text = response["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert "recommended_model_id" in payload
    assert "advisory" in payload
