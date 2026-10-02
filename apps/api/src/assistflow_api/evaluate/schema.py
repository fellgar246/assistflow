"""Scenario file shape. Ids stay stable across prompt and tool edits."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScenarioCategory(StrEnum):
    POLICY_QA = "policy_qa"
    ORDER_LOOKUP = "order_lookup"
    SHIPMENT_LOOKUP = "shipment_lookup"
    UNSUPPORTED_QUESTION = "unsupported_question"
    RETURN_REQUEST = "return_request"
    REFUND_REQUEST = "refund_request"
    ADDRESS_CHANGE = "address_change"
    PROMPT_INJECTION = "prompt_injection"
    TENANT_CROSSOVER = "tenant_crossover"
    TOOL_FAILURE = "tool_failure"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    HUMAN_ESCALATION = "human_escalation"


MINIMUM_COUNTS: dict[ScenarioCategory, int] = {
    ScenarioCategory.POLICY_QA: 15,
    ScenarioCategory.ORDER_LOOKUP: 10,
    ScenarioCategory.SHIPMENT_LOOKUP: 10,
    ScenarioCategory.UNSUPPORTED_QUESTION: 8,
    ScenarioCategory.RETURN_REQUEST: 10,
    ScenarioCategory.REFUND_REQUEST: 10,
    ScenarioCategory.ADDRESS_CHANGE: 10,
    ScenarioCategory.PROMPT_INJECTION: 12,
    ScenarioCategory.TENANT_CROSSOVER: 8,
    ScenarioCategory.TOOL_FAILURE: 7,
    ScenarioCategory.AMBIGUOUS_REQUEST: 5,
    ScenarioCategory.HUMAN_ESCALATION: 5,
}

MINIMUM_TOTAL = 100

METRIC_NAMES: tuple[str, ...] = (
    "correct_tool_selected",
    "correct_tool_arguments",
    "forbidden_tool_not_called",
    "approval_required_when_expected",
    "no_cross_tenant_access",
    "source_present_for_policy_answer",
    "numeric_and_order_facts_preserved",
    "max_steps_respected",
)

SAFETY_METRICS: tuple[str, ...] = (
    "forbidden_tool_not_called",
    "approval_required_when_expected",
    "no_cross_tenant_access",
    "max_steps_respected",
)

QUALITATIVE_METRICS: tuple[str, ...] = (
    "groundedness",
    "helpfulness",
    "clarity",
    "policy_compliance",
    "escalation_appropriateness",
)


class FixtureOverrides(BaseModel):
    """Optional knobs for one scenario. An empty object changes nothing."""

    model_config = ConfigDict(extra="forbid")

    fail_tool: str | None = None


class Expectation(BaseModel):
    """What a passing turn looks like. Argument checks are subsets."""

    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(default_factory=list)
    arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    approval_required: bool = False
    confirm: bool = False
    source_required: bool = False
    preserve_facts: list[str] = Field(default_factory=list)
    abstain: bool = False
    tool_error: str | None = None
    forbid_unretrieved_facts: bool = False
    forbidden_facts: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=8, ge=1)


class Scenario(BaseModel):
    """One golden turn. The id is the stable key in every report."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=3, max_length=80)
    category: ScenarioCategory
    tenant_id: UUID
    customer_id: UUID
    utterance: str = Field(min_length=1, max_length=2000)
    fixture_overrides: FixtureOverrides = Field(default_factory=FixtureOverrides)
    expect: Expectation
