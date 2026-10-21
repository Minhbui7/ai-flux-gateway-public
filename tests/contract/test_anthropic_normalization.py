"""Execute exact policy C# using a .NET SDK or PowerShell's offline compiler.

This checks expression syntax and behavior, not APIM's policy-expression allowlist.
"""

import copy
import json
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = {"type": "text", "text": "Library answer."}
THINKING = {"type": "thinking", "thinking": "SYNTHETIC_INTERNAL", "signature": "SYNTHETIC_SIGNATURE"}
BASE = {
    "id": "synthetic-message",
    "content": [TEXT],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 17, "output_tokens": 503},
}


def response(**changes):
    return copy.deepcopy(BASE | changes)


VALID = {
    "text": (response(), "Library answer.", "stop"),
    "multiple-text": (
        response(content=[TEXT, {"type": "text", "text": " More."}]),
        "Library answer. More.",
        "stop",
    ),
    "thinking-text": (response(content=[THINKING, TEXT]), "Library answer.", "stop"),
    "mixed-order": (
        response(content=[TEXT, THINKING, {"type": "text", "text": " More."}]),
        "Library answer. More.",
        "stop",
    ),
    "empty-thinking": (response(content=[THINKING | {"thinking": ""}, TEXT]), "Library answer.", "stop"),
    "stop-sequence": (response(stop_reason="stop_sequence"), "Library answer.", "stop"),
    "max-tokens": (response(stop_reason="max_tokens"), "Library answer.", "length"),
    "ceiling": (response(usage={"input_tokens": 17, "output_tokens": 100000}), "Library answer.", "stop"),
    "zero-usage": (response(usage={"input_tokens": 0, "output_tokens": 0}), "Library answer.", "stop"),
}
INVALID = {
    "empty-content": response(content=[]),
    "non-array-content": response(content=TEXT),
    "thinking-only": response(content=[THINKING]),
    "empty-answer": response(content=[TEXT | {"text": ""}]),
    "whitespace-answer": response(content=[TEXT | {"text": " \n\t"}]),
    "text-null": response(content=[TEXT | {"text": None}]),
    "text-numeric": response(content=[TEXT | {"text": 1}]),
    "text-missing": response(content=[{"type": "text"}]),
    "non-object-block": response(content=[None, TEXT]),
    "array-block": response(content=[[], TEXT]),
    "string-block": response(content=["text", TEXT]),
    "type-missing": response(content=[{"text": "Answer."}]),
    "type-null": response(content=[TEXT | {"type": None}]),
    "type-numeric": response(content=[TEXT | {"type": 1}]),
    "thinking-missing": response(content=[{"type": "thinking", "signature": "synthetic"}, TEXT]),
    "thinking-nonstring": response(content=[THINKING | {"thinking": {}}, TEXT]),
    "signature-missing": response(content=[{"type": "thinking", "thinking": ""}, TEXT]),
    "signature-null": response(content=[THINKING | {"signature": None}, TEXT]),
    "signature-numeric": response(content=[THINKING | {"signature": 1}, TEXT]),
    "signature-empty": response(content=[THINKING | {"signature": ""}, TEXT]),
    "signature-whitespace": response(content=[THINKING | {"signature": " \n"}, TEXT]),
    "tool": response(content=[{"type": "tool_use", "id": "synthetic", "name": "tool", "input": {}}, TEXT]),
    "unknown": response(content=[{"type": "future_block"}, TEXT]),
    "unconfirmed-redacted-thinking": response(
        content=[{"type": "redacted_thinking", "data": "synthetic"}, TEXT]
    ),
    "id-null": response(id=None),
    "id-empty": response(id=""),
    "id-whitespace": response(id=" "),
    "id-numeric": response(id=123),
    "usage-null": response(usage=None),
    "usage-missing-output": response(usage={"input_tokens": 17}),
    "usage-negative-input": response(usage={"input_tokens": -1, "output_tokens": 503}),
    "usage-negative-output": response(usage={"input_tokens": 17, "output_tokens": -1}),
    "usage-float": response(usage={"input_tokens": 17, "output_tokens": 503.0}),
    "usage-string": response(usage={"input_tokens": "17", "output_tokens": 503}),
    "usage-boolean": response(usage={"input_tokens": True, "output_tokens": 503}),
    "over-ceiling": response(usage={"input_tokens": 17, "output_tokens": 100001}),
    "usage-int-overflow": response(usage={"input_tokens": 2**31, "output_tokens": 503}),
    "usage-total-overflow": response(usage={"input_tokens": 2**31 - 1, "output_tokens": 503}),
    "stop-null": response(stop_reason=None),
    "stop-object": response(stop_reason={}),
    "stop-tool": response(stop_reason="tool_use"),
    "stop-pause": response(stop_reason="pause_turn"),
    "stop-refusal": response(stop_reason="refusal"),
    "stop-unknown": response(stop_reason="future_reason"),
}
INVALID["id-missing"] = response()
del INVALID["id-missing"]["id"]
INVALID["stop-missing"] = response()
del INVALID["stop-missing"]["stop_reason"]


def execute_expression(tmp_path_factory, expression, fixtures):
    dotnet = os.environ.get("AIFLUX_DOTNET", shutil.which("dotnet"))
    pwsh = shutil.which("pwsh")
    sdk = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True,
                         timeout=30) if dotnet else None
    has_sdk = sdk is not None and sdk.returncode == 0 and bool(sdk.stdout.strip())
    assert has_sdk or pwsh, "A .NET SDK or PowerShell 7 C# compiler is required."
    assert expression.startswith("@{") and expression.endswith("}")
    expression = expression[1:].replace("${completion_token_limit}", "100000")
    expression = expression.replace(
        "${anthropic_context_conditions}",
        '(string)context.Variables["aiflux-model"] == "claude-haiku-5-5" || '
        '(string)context.Variables["aiflux-model"] == "claude-sonnet-5-5" || '
        '(string)context.Variables["aiflux-model"] == "claude-opus-5-5"',
    )
    harness = ROOT / (".policy-csharp-" + uuid.uuid4().hex)
    harness.mkdir()
    (harness / "Harness.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        "<TargetFramework>net8.0</TargetFramework></PropertyGroup><ItemGroup>"
        '<PackageReference Include="Newtonsoft.Json" Version="13.0.3" />'
        "</ItemGroup></Project>",
        encoding="utf-8",
    )
    (harness / "Program.cs").write_text(
        r"""
using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

public class PolicyBody {
    public string Json;
    public object Value;
    public T As<T>(bool preserveContent) { return Value == null ? JsonConvert.DeserializeObject<T>(Json) : (T)Value; }
}
public class PolicyResponse { public PolicyBody Body; }
public class PolicyContext {
    public PolicyResponse Response;
    public Dictionary<string, object> Variables = new Dictionary<string, object> {
        { "aiflux-model", "claude-haiku-5-5" },
        { "aiflux-backend-attempt", 1 },
        { "aiflux-request-json", "{\"max_completion_tokens\":100000}" }
    };
}
public class Normalizer {
    private PolicyContext context = new PolicyContext();
    public string Execute(JObject response) {
        context.Variables["aiflux-model"] = (string)response["_alias"] ?? "claude-haiku-5-5";
        context.Variables["aiflux-backend-attempt"] = (int?)response["_attempts"] ?? 1;
        if (response["_rawSurrogate"] != null) {
            response["choices"][0]["message"]["content"] = new string((char)(int)response["_rawSurrogate"], 1);
        }
        context.Response = new PolicyResponse { Body = new PolicyBody {
            Json = response["_rawBody"] == null ? response.ToString() : (string)response["_rawBody"],
            Value = response["_rawBody"] == null ? response : null
        } };
        return Normalize();
    }
    private string Normalize()
"""
        + expression
        + """
}
public class Program {
    public static void Main() {
        var results = new JObject();
        foreach (var fixture in JObject.Parse(Console.In.ReadToEnd()).Properties()) {
            try {
                results[fixture.Name] = JToken.Parse(new Normalizer().Execute((JObject)fixture.Value));
            } catch (Exception) {
                results[fixture.Name] = new JObject { ["rejected"] = true };
            }
        }
        Console.WriteLine(results.ToString(Formatting.None));
    }
}
""",
        encoding="utf-8",
    )
    env = os.environ | {"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    try:
        if has_sdk:
            build = subprocess.run(
                [dotnet, "build", str(harness / "Harness.csproj"), "--verbosity", "quiet"],
                capture_output=True, text=True, env=env, timeout=180,
            )
            assert build.returncode == 0, build.stdout + build.stderr
            command = [dotnet, str(harness / "bin" / "Debug" / "net8.0" / "Harness.dll")]
        else:
            # PowerShell ships Newtonsoft and Roslyn; only suppress its runtime-version unification warning.
            script = harness / "Run.ps1"
            script.write_text(
                '$ErrorActionPreference = "Stop"\n'
                '$references = @(Get-ChildItem "$PSHOME\\ref\\*.dll" | ForEach-Object FullName)\n'
                '$references += [Newtonsoft.Json.Linq.JObject].Assembly.Location\n'
                'Add-Type -TypeDefinition (Get-Content -LiteralPath '
                '"$PSScriptRoot\\Program.cs" -Raw) -ReferencedAssemblies $references '
                '-CompilerOptions "/nowarn:1701"\n'
                '[Program]::Main()\n',
                encoding="utf-8",
            )
            command = [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script)]
        execution = subprocess.run(
            command, input=json.dumps(fixtures), capture_output=True,
            text=True, encoding="utf-8", env=env, timeout=60,
        )
        assert execution.returncode == 0, execution.stdout + execution.stderr
        return json.loads(execution.stdout)
    finally:
        shutil.rmtree(harness)


def protected_response(*texts):
    return {"choices": [{"message": {"content": text}} for text in texts]}


PROTECTED_VALID = {
    "over-9000": "a" * 9001,
    "ascii-cap-last-overlap": "a" * 35200 + "LAST" + "b" * 796,
    "surrogate-cap": "😀" * 18000,
    "surrogate-at-step": "a" * 8799 + "😀" + "b" * 18000,
    "surrogate-at-end": "a" * 8999 + "😀" + "b" * 18000,
    "surrogate-at-last-overlap": "a" * 35199 + "😀" + "z" * 799,
    "empty-text": "",
}


@pytest.fixture(scope="module")
def protected_chunks(tmp_path_factory):
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    expression = policy.find(".//set-variable[@name='aiflux-protected-chunks']").get("value")
    invalid = {
        "overcap": protected_response("a" * 36001),
        "surrogate-overcap": protected_response("😀" * 18001),
        "all-choices-overcap": protected_response("a" * 18000, "b" * 18000),
        "missing-choices": {},
        "null-choices": {"choices": None},
        "not-array": {"choices": {}},
        "no-choices": {"choices": []},
        "nonobject-choice": {"choices": ["answer"]},
        "null-message": {"choices": [{"message": None}]},
        "missing-content": {"choices": [{"message": {}}]},
        "null-content": protected_response(None),
        "nontext-content": protected_response([{"type": "text", "text": "answer"}]),
        "nontext-later-choice": protected_response("valid first", 42),
        "malformed-json": {"_rawBody": "{not-json"},
        "null-json": {"_rawBody": "null"},
        "unpaired-high-surrogate": protected_response("placeholder") | {"_rawSurrogate": 0xD800},
        "unpaired-low-surrogate": protected_response("placeholder") | {"_rawSurrogate": 0xDC00},
    }
    for field in ("tool_calls", "function_call", "audio"):
        item = protected_response("text", "another")
        item["choices"][1]["message"][field] = {}
        invalid[field] = item
    fixtures = {name: protected_response(text) for name, text in PROTECTED_VALID.items()} | invalid
    fixtures["multiple-choices"] = protected_response("first" * 1800, "😀" * 5000, "last answer")
    return execute_expression(tmp_path_factory, expression, fixtures), invalid


@pytest.mark.parametrize("name", PROTECTED_VALID)
def test_exact_protected_chunks_cover_all_unicode_and_boundaries(protected_chunks, name):
    results, _ = protected_chunks
    chunks = results[name]
    assert isinstance(chunks, list) and len(chunks) <= 5
    assert all(len(chunk) <= 9000 for chunk in chunks)
    for left, right in zip(chunks, chunks[1:]):
        assert left[-200:] == right[:200]
    rebuilt = chunks[0] + "".join(chunk[200:] for chunk in chunks[1:]) if chunks else ""
    assert rebuilt == PROTECTED_VALID[name]
    if name == "ascii-cap-last-overlap":
        assert len(chunks) == 5 and len(chunks[-1]) == 800


def test_exact_protected_chunks_scan_all_choices_not_only_prefix(protected_chunks):
    results, _ = protected_chunks
    chunks = results["multiple-choices"]
    rebuilt = chunks[0] + "".join(chunk[200:] for chunk in chunks[1:])
    assert rebuilt == "first" * 1800 + "\n" + "😀" * 5000 + "\nlast answer"
    assert len(chunks) > 1 and chunks[-1].endswith("last answer")
    assert all(len(chunk) <= 9000 for chunk in chunks)
    assert all(left[-200:] == right[:200] for left, right in zip(chunks, chunks[1:]))


def test_exact_protected_chunks_reject_malformed_nontext_and_overcap(protected_chunks):
    results, invalid = protected_chunks
    assert all(results[name] == {"rejected": True} for name in invalid)


def test_exact_invariant_safety_floor_truth_table(tmp_path_factory):
    source = (ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl").read_text()
    entries, expected = [], {}
    for allowed in (False, True):
        for runtime in (False, True):
            rendered = source.replace("${safety_relaxation_allowed}", str(allowed).lower())
            for name in ("input_filter_expr", "output_filter_expr", "prompt_shield"):
                rendered = rendered.replace("${" + name + "}", str(runtime).lower())
            policy = ET.fromstring(rendered)
            expressions = [node.get("condition") for node in policy.findall(".//when")
                           if f'!{str(allowed).lower()} || ({str(runtime).lower()})'
                           in node.get("condition", "")]
            expressions += [node.get("shield-prompt") for node in
                            policy.findall(".//llm-content-safety")[:2]]
            assert len(expressions) == 5
            for index, expression in enumerate(expressions):
                key = f"{allowed}-{runtime}-{index}"
                expression = expression[2:-1].replace('context.Request.Method', '"POST"')
                entries.append(f'["{key}"] = ({expression})')
                expected[key] = not allowed or runtime
    expression = '@{ return new JObject { ' + ', '.join(entries) + ' }.ToString(); }'
    assert execute_expression(tmp_path_factory, expression, {"floor": {}})["floor"] == expected


@pytest.fixture(scope="module")
def normalized(tmp_path_factory):
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    expression = policy.find(".//set-body[@id='aiflux-anthropic-normalization']").text
    return execute_expression(
        tmp_path_factory,
        expression,
        {name: value[0] for name, value in VALID.items()} | INVALID,
    )


def test_exact_usage_expression_keeps_only_valid_metadata(tmp_path_factory):
    policy = ET.parse(ROOT / "gateway" / "policies" / "dev-openai.xml.tftpl")
    expression = policy.find(".//set-variable[@name='aiflux-finops-usage']").attrib["value"]
    fixtures = {
        "openai": {
            "_alias": "gpt-5.6-sol",
            "content": "SYNTHETIC_DO_NOT_LOG",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        },
        "anthropic": {
            "_attempts": 2,
            "content": [THINKING, TEXT],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 10,
            },
        },
        "invalid": {
            "usage": {
                "input_tokens": True,
                "output_tokens": -1,
                "cache_read_input_tokens": 2**31,
                "cache_creation_input_tokens": "10",
            },
        },
        "missing": {},
    }
    results = execute_expression(tmp_path_factory, expression, fixtures)
    assert results["openai"] == {
        "schema": "finops-v1",
        "model": "gpt-5.6-sol",
        "attempts": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 40,
        "cache_write_tokens": None,
    }
    assert results["anthropic"] == {
        "schema": "finops-v1",
        "model": "claude-haiku-5-5",
        "attempts": 2,
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 40,
        "cache_write_tokens": 10,
    }
    for name in ("missing", "invalid"):
        assert all(
            results[name][key] is None
            for key in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
            )
        )
    assert "SYNTHETIC" not in json.dumps(results)


@pytest.mark.parametrize("name", VALID)
def test_supported_shapes_keep_only_answer_and_full_usage(normalized, name):
    provider, answer, finish = VALID[name]
    actual = normalized[name]
    assert actual["object"] == "chat.completion"
    assert actual["model"] == "claude-haiku-5-5"
    assert actual["id"] == provider["id"]
    assert isinstance(actual["created"], int)
    assert actual["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": finish,
        }
    ]
    assert actual["usage"] == {
        "prompt_tokens": provider["usage"]["input_tokens"],
        "completion_tokens": provider["usage"]["output_tokens"],
        "total_tokens": sum(provider["usage"].values()),
    }
    assert "SYNTHETIC_INTERNAL" not in json.dumps(actual)
    assert "SYNTHETIC_SIGNATURE" not in json.dumps(actual)


@pytest.mark.parametrize("name", INVALID)
def test_unsupported_shapes_fail_closed(normalized, name):
    assert normalized[name] == {"rejected": True}
