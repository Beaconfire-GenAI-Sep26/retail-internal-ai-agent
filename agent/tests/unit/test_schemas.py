import json

import pytest
from pydantic import ValidationError

from app.llm.schemas import parse_reason_output, reason_output_schema, schema_hash
from tests.scripts import store_a_turns, store_b_turns


def walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


def test_schema_has_exactly_two_unions():
    assert json.dumps(reason_output_schema()).count('"anyOf"') == 2


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
    assert defs["ClaimSampleRequestWire"]["properties"]["evidence_type"]["enum"] == ["claim"]


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
