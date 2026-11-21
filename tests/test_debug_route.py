import pytest


@pytest.mark.parametrize(
    ("kind", "status", "category"),
    [
        ("validation", 422, "validation"),
        ("auth", 401, "auth"),
        ("domain", 404, "domain"),
        ("database", 503, "database"),
        ("external", 504, "external"),
        ("internal", 500, "internal"),
        ("unhandled", 500, "internal"),
    ],
)
def test_debug_route_raises_each_category_locally(make_client, kind, status, category) -> None:
    response = make_client("local").get(f"/_debug/errors/{kind}")

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["category"] == category


def test_unhandled_kind_is_a_real_unknown_exception(make_client) -> None:
    body = make_client("local").get("/_debug/errors/unhandled").json()

    assert body["code"] == "INTERNAL_ERROR"
    assert body["debug"]["type"] == "RuntimeError"


def test_unknown_kind_is_a_validation_error(make_client) -> None:
    response = make_client("local").get("/_debug/errors/nonsense")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_debug_route_does_not_exist_outside_local(make_client, environment) -> None:
    response = make_client(environment).get("/_debug/errors/internal")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
