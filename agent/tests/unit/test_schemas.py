import json

import pytest
from pydantic import ValidationError

from agent.app.llm.schemas import parse_reason_output, reason_output_schema, schema_hash
from agent.tests.scripts import store_a_turns, store_b_turns


def walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


def test_schema_has_one_union_and_sends_the_request_as_a_string():
    # The API's grammar compiler rejects the 8 request shapes as one union, so the request is a JSON string.
    schema = reason_output_schema()
    assert json.dumps(schema).count('"anyOf"') == 1
    assert schema["$defs"]["CheckPlanWire"]["properties"]["request"]["type"] == "string"
    assert not [name for name in schema["$defs"] if name.endswith("RequestWire")]


def test_every_object_is_closed_and_fully_required():
    for path, node in walk(reason_output_schema()):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert set(node.get("properties", {})) == set(node.get("required", [])), path


def test_no_const_survives_and_tags_are_enums():
    text = json.dumps(reason_output_schema())
    assert "const" not in text
    defs = reason_output_schema()["$defs"]
    assert defs["CheckAction"]["properties"]["type"]["enum"] == ["check"]
    assert defs["ConcludeAction"]["properties"]["type"]["enum"] == ["conclude"]


def test_no_numeric_or_length_constraints():
    for path, node in walk(reason_output_schema()):
        for key in ("minimum", "maximum", "minLength", "maxLength", "exclusiveMinimum", "pattern"):
            assert key not in node, path


def test_schema_hash_is_stable():
    assert schema_hash() == schema_hash()
    assert len(schema_hash()) == 16


@pytest.mark.parametrize("turn", [*store_a_turns(), *store_b_turns()])
def test_script_turns_are_valid_outputs(turn):
    parse_reason_output(turn)


def test_enum_values_are_lowercased_before_validation():
    turn = json.loads(json.dumps(store_a_turns()[0]))
    turn["next_action"]["type"] = "CHECK"
    turn["next_action"]["plan"]["kind"] = "Explore"
    turn["new_hypotheses"][0]["cause_category"] = "POS_MODIFIER_MAPPING"
    parsed = parse_reason_output(turn)
    assert parsed.next_action.type == "check"
    assert parsed.next_action.plan.kind == "explore"
    assert parsed.new_hypotheses[0].cause_category == "pos_modifier_mapping"


def test_union_picks_the_variant_by_its_tags():
    turn = json.loads(json.dumps(store_a_turns()[3]))
    parsed = parse_reason_output(turn)
    assert type(parsed.next_action.plan.request).__name__ == "ComparePeriodsRequestWire"


def test_extra_fields_are_rejected():
    turn = json.loads(json.dumps(store_a_turns()[0]))
    turn["unexpected"] = 1
    with pytest.raises(ValidationError):
        parse_reason_output(turn)


def with_request(request):
    turn = json.loads(json.dumps(store_a_turns()[3]))
    turn["next_action"]["plan"]["request"] = request
    return turn


def test_a_request_string_is_decoded_and_left_out_filters_mean_no_constraint():
    request = json.dumps({"tool": "compare_periods", "split_date": "2026-10-30", "days_before": 14, "days_after": 17,
                          "target": {"modifiers": ["Extra sauce"]}})
    parsed = parse_reason_output(with_request(request)).next_action.plan.request
    assert type(parsed).__name__ == "ComparePeriodsRequestWire"
    assert parsed.control_mode == "rest_of_store" and parsed.target.daypart == [] and parsed.target.item_count_min == 0


def test_samples_pick_their_model_by_evidence_type():
    request = json.dumps({"tool": "Sample_Evidence", "evidence_type": "cancellation", "limit": 3,
                          "filter": {"start": "2026-10-05", "end": "2026-11-15", "cancellation_category": ["too_busy"]}})
    parsed = parse_reason_output(with_request(request)).next_action.plan.request
    assert type(parsed).__name__ == "CancellationSampleRequestWire"


@pytest.mark.parametrize(("request_text", "expected"), [
    ('{"tool": "claim_breakdown", "filter": {"start": "2026-10-05"', "not valid JSON"),
    ('["claim_breakdown"]', "JSON object"),
    ('{"tool": "order_lookup", "start": "2026-10-05", "end": "2026-11-15"}', "tool must be one of"),
    ('{"tool": "claim_breakdown", "filter": {"start": "2026-10-05", "end": "2026-11-15"}}', "group_by"),
    ('{"tool": "claim_breakdown", "filter": {"start": "2026-10-05", "end": "2026-11-15", "shift": ["dinner"]}, '
     '"group_by": "modifier"}', "shift"),
])
def test_a_bad_request_names_the_problem(request_text, expected):
    with pytest.raises(ValidationError) as info:
        parse_reason_output(with_request(request_text))
    assert expected in str(info.value)
