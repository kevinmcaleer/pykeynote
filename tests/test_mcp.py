import io
import json

from pykeynote import Presentation
from pykeynote.mcp import Server, serve


def request(server, method, params=None, id=1):
    return server.handle({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def call(server, name, **arguments):
    return request(server, "tools/call", {"name": name, "arguments": arguments})["result"]


def test_initialize_negotiates_version():
    server = Server()
    result = request(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                            "clientInfo": {"name": "t", "version": "0"}})["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == "pykeynote"
    assert "tools" in result["capabilities"]
    old = request(Server(), "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert old["protocolVersion"] == "2025-06-18"


def test_notifications_get_no_reply():
    assert Server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list():
    tools = request(Server(), "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"deck_info", "read_slide", "edit_slide", "add_slide", "move_slide", "delete_slide",
            "create_deck", "export_markdown"} <= names
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["description"]
    info = next(t for t in tools if t["name"] == "deck_info")
    assert info["annotations"]["readOnlyHint"] is True


def test_tool_calls(tmp_path):
    server = Server()
    path = str(tmp_path / "talk.key")
    result = call(server, "create_deck", path=path, markdown="# Hello\n\n- one\n- two")
    assert not result["isError"]
    assert result["structuredContent"]["slide_count"] == 1
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]

    result = call(server, "edit_slide", path=path, index=0, title="Hi", body=[{"text": "x", "level": 1}])
    assert not result["isError"]
    assert Presentation.open(path)[0].title == "Hi"

    result = call(server, "export_markdown", path=path)
    assert "# Hi" in result["structuredContent"]["markdown"]


def test_tool_errors_are_results(tmp_path):
    server = Server()
    result = call(server, "read_slide", path=str(tmp_path / "missing.key"), index=0)
    assert result["isError"]
    assert "no such deck" in result["content"][0]["text"]
    assert call(server, "read_slide", path="x.key")["isError"]  # missing index
    assert call(server, "deck_info", path="x.key", bogus=1)["isError"]
    reply = request(server, "tools/call", {"name": "nope"})
    assert reply["error"]["code"] == -32602


def test_unknown_method():
    assert request(Server(), "resources/list")["error"]["code"] == -32601


def test_serve_over_stdio(tmp_path):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_themes"}},
    ]
    stdin = io.StringIO("\n".join(json.dumps(m) for m in lines) + "\nnot json\n")
    stdout = io.StringIO()
    serve(stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, None]
    assert "Basic White" in replies[1]["result"]["structuredContent"]["themes"]
    assert replies[2]["error"]["code"] == -32700
