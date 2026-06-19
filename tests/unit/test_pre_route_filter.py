from app.models.task import Task
from app.services.pre_route_filter import classify_tasks


def _stop(
    label: str,
    *,
    task_id: str = "task_1",
    brand: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> Task:
    payload = {"label": label, "query": label, "original_text": label}
    if brand is not None:
        payload["brand"] = brand
    if lat is not None:
        payload["lat"] = lat
    if lng is not None:
        payload["lng"] = lng
    return Task(
        id=task_id,
        type="stop",
        name=None,
        brand=brand,
        constraints=None,
        order_hint=1,
        payload=payload,
    )


def _destination(name: str) -> Task:
    return Task(
        id="task_dest",
        type="destination",
        name=name,
        brand=None,
        constraints=None,
        order_hint=2,
    )


def test_vague_food_stop_requires_clarification() -> None:
    decision = classify_tasks([_stop("food")], "I want food")

    assert decision.status == "clarification_needed"
    assert decision.trigger_task_id == "task_1"
    assert decision.clarification_domain == "food"
    assert decision.question == "What type of food are you looking for?"


def test_delegated_vague_stop_surfaces_candidates() -> None:
    decision = classify_tasks([_stop("restaurant")], "Just find me somewhere to eat")

    assert decision.status == "candidate_selection_needed"
    assert decision.trigger_task_id == "task_1"
    assert decision.candidate_query == "restaurant"
    assert decision.is_delegation is True


def test_brand_stop_surfaces_candidate_selection() -> None:
    decision = classify_tasks([_stop("Starbucks", brand="Starbucks")], "Find Starbucks on the way")

    assert decision.status == "candidate_selection_needed"
    assert decision.candidate_query == "Starbucks"
    assert decision.is_delegation is False


def test_resolved_stop_is_ready_for_routing() -> None:
    tasks = [_stop("Starbucks", lat=52.94, lng=-1.19), _destination("East Midlands Airport")]

    decision = classify_tasks(tasks, "Use this Starbucks")

    assert decision.status == "ready_for_routing"


def test_unique_named_stop_is_ready_for_routing() -> None:
    decision = classify_tasks([_stop("Nottingham Castle")], "Stop by Nottingham Castle")

    assert decision.status == "ready_for_routing"

