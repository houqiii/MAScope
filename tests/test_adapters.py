import pytest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "mascope_external_adapters", Path(__file__).parents[1] / "adapters/convert.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HOOKS, adapt = module.HOOKS, module.adapt
from mascope.events import KINDS, normalize_events


@pytest.mark.parametrize("method", HOOKS)
def test_native_hooks_preserve_visible_context_and_order(method):
    recruit, assign, aggregate, submit = HOOKS[method]
    context = ["peer result [MS-000000000001] timeout=30"]
    records = [
        {"hook": recruit, "agent_id": "a"},
        {
            "hook": assign,
            "agent_id": "a",
            "instruction": "follow up",
            "carried_units": context,
        },
        {"kind": "local_output", "agent_id": "a", "text": "done", "evidence_ids": []},
        {"hook": aggregate, "text": "merge"},
        {"hook": submit, "text": "answer"},
    ]
    events = adapt(method, records)
    assert all(e["kind"] in KINDS for e in events)
    assert [e["event_id"] for e in events] == [f"e{i:06d}" for i in range(1, 6)]
    assert events[1]["carried_units"] == context
    assert normalize_events(events)[-1]["text"] == "answer"
    with pytest.raises(ValueError, match="visible"):
        adapt(
            method,
            [{"hook": assign, "agent_id": "a", "instruction": "missing context"}],
        )


def test_pool_registration_does_not_count_all_agents():
    records = [
        {
            "hook": HOOKS["MoA"][1],
            "agent_id": "used",
            "instruction": "work",
            "carried_units": [],
        }
    ]
    events = adapt("MoA", records)
    assert [(e["kind"], e["agent_id"]) for e in events] == [
        ("recruit", "used"),
        ("assign", "used"),
    ]


def test_group_assignment_and_combined_turn_are_unpacked():
    events = adapt(
        "LangGraph",
        [
            {
                "hook": "coordinator_turn",
                "aggregate": {
                    "actor": "manager",
                    "inputs": ["previous"],
                    "output": "combined",
                },
                "assignments": [
                    {
                        "to": ["a", "b"],
                        "instruction": "work",
                        "carried_units": ["combined"],
                    }
                ],
            }
        ],
    )
    assert events[0]["kind"] == "aggregate"
    assert [e["to"] for e in events if e["kind"] == "assign"] == ["a", "b"]
    assert all(
        e["carried_units"] == ["combined"] for e in events if e["kind"] == "assign"
    )


def test_staffed_method_does_not_invent_missing_recruitment():
    events = adapt(
        "GoA",
        [
            {
                "hook": HOOKS["GoA"][1],
                "agent_id": "node",
                "instruction": "work",
                "carried_units": [],
            }
        ],
    )
    assert [e["kind"] for e in events] == ["assign"]
