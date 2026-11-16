"""Terminology matching tests use fake DynamoDB responses, never AWS."""

from unittest.mock import Mock

import pytest

from src.services.terminology_service import TerminologyService, TerminologyError
from src.storage.terminology_repository import TerminologyRepository


def term(source, target=None, catalog="a", ident="1", updated="2026-01-01"):
    return dict(
        source_term=source,
        target_term=target or source,
        catalog_id=catalog,
        id=ident,
        updated_at=updated,
        language_pair_id="lp",
    )


class FakeRepository:
    def __init__(self, catalogs=None, terms=None):
        self.catalogs = catalogs or [dict(id="a", name="A", language_pair_id="lp")]
        self.terms = terms or {}

    async def catalogs_page(self, language_pair_id, limit, last_key=None):
        return self.catalogs, None, len(self.catalogs)

    async def get_catalog(self, language_pair_id, catalog_id):
        return next(
            (
                c
                for c in self.catalogs
                if c["id"] == catalog_id and c["language_pair_id"] == language_pair_id
            ),
            None,
        )

    async def get_language_pair(self, language_pair_id):
        return None

    async def terms_page(self, catalog_id, limit, last_key=None):
        items = self.terms.get(catalog_id, [])
        return items, None, len(items)


async def test_unicode_boundaries_overlaps_and_order():
    repo = FakeRepository(
        terms={
            "a": [
                term(s)
                for s in ["cat", "café", "máy", "数据库", "数据库连接", "CAT", "2"]
            ]
        }
    )
    result = await TerminologyService(repo).match_terminology(
        "catalog cat猫 cafe\u0301 máy móc máyx 数据库连接 x2 2", "lp"
    )
    assert [t["source_term"] for t in result["terms"]] == [
        "cat",
        "café",
        "máy",
        "数据库连接",
        "数据库",
        "2",
    ]
    assert result["total_matches"] == 6
    assert result["truncated"] is False


async def test_conflict_priority_normalization_and_truncation():
    catalogs = [dict(id=c, name=c, language_pair_id="lp") for c in ["b", "a"]]
    repo = FakeRepository(
        catalogs,
        {
            "a": [
                term("café", "old", ident="z"),
                term("cafe\u0301", "new", ident="z", updated="2026-02-01"),
                term("café", "winner", ident="a", updated="2026-02-01"),
            ],
            "b": [term("café", "B", catalog="b"), term("cat", catalog="b")],
        },
    )
    service = TerminologyService(repo)
    default = await service.match_terminology("café cat", "lp", max_results=1)
    assert default == dict(
        terms=[dict(source_term="café", target_term="winner", catalog_id="a")],
        total_matches=2,
        truncated=True,
    )
    explicit = await service.match_terminology("café", "lp", ["b", "a", "b"])
    assert explicit["terms"][0]["target_term"] == "B"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(text=" "),
        dict(language_pair_id=""),
        dict(catalog_ids=[]),
        dict(catalog_ids=["missing"]),
        dict(max_results=0),
        dict(text="x" * 50001),
        dict(catalog_ids=["a"] * 21),
    ],
)
async def test_invalid_arguments(kwargs):
    arguments = dict(text="cat", language_pair_id="lp") | kwargs
    with pytest.raises(TerminologyError):
        await TerminologyService(FakeRepository()).match_terminology(**arguments)


class Table:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)

    scan = query

    def get_item(self, **kwargs):
        self.calls.append(kwargs)
        return {"Item": dict(id="a", name="A", language_pair_id="lp")}


def aws_repository(catalog_pages, term_pages):
    catalogs, terms = Table(catalog_pages), Table(term_pages)
    shared = Mock()
    shared._get_resource.return_value.Table.side_effect = lambda name: (
        catalogs if name.endswith("catalogs") else terms
    )

    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)

    shared._run_sync = run
    return TerminologyRepository(shared), catalogs, terms


async def test_real_pagination_beyond_1000_and_full_catalog_discovery():
    key = {"pk": "LP#lp", "sk": "CAT#a"}
    term_key = {"pk": "p", "sk": "t"}
    repo, catalogs, terms = aws_repository(
        [
            {"Items": [], "LastEvaluatedKey": key},
            {"Items": [dict(id="a", name="A", language_pair_id="lp")]},
        ],
        [
            {
                "Items": [term(f"absent{i}") for i in range(1000)],
                "LastEvaluatedKey": term_key,
            },
            {"Items": [term("needle", "FOUND")]},
        ],
    )
    result = await TerminologyService(repo).match_terminology("needle", "lp")
    assert result["terms"][0]["target_term"] == "FOUND"
    assert catalogs.calls[1]["ExclusiveStartKey"] == key
    assert terms.calls[1]["ExclusiveStartKey"] == term_key


async def test_catalog_cursor_preserves_database_key_and_filter():
    key = {"pk": "LP#lp", "sk": "CAT#a"}
    repo, catalogs, _ = aws_repository(
        [
            {
                "Items": [dict(id="a", name="A", language_pair_id="lp")],
                "LastEvaluatedKey": key,
            },
            {"Items": []},
        ],
        [],
    )
    service = TerminologyService(repo)
    result = await service.list_catalogs("lp", page_size=1)
    assert result["items"] == [
        dict(
            catalog_id="a",
            name="A",
            language_pair_id="lp",
            source_language=None,
            target_language=None,
        )
    ]
    await service.list_catalogs("lp", page_size=1, cursor=result["next_cursor"])
    assert catalogs.calls[1]["ExclusiveStartKey"] == key
    with pytest.raises(TerminologyError):
        await service.list_catalogs("other", cursor=result["next_cursor"])


async def test_resource_budget_includes_catalogs_and_terms():
    service = TerminologyService(
        FakeRepository(terms={"a": [term("cat")]}), max_records=1
    )
    with pytest.raises(TerminologyError, match="RESOURCE_LIMIT"):
        await service.match_terminology("cat", "lp")


async def test_dependency_failure_does_not_return_empty_success():
    from botocore.exceptions import EndpointConnectionError

    repo, catalogs, _ = aws_repository([], [])
    catalogs.query = Mock(side_effect=EndpointConnectionError(endpoint_url="test"))
    with pytest.raises(TerminologyError, match="DEPENDENCY_UNAVAILABLE"):
        await TerminologyService(repo).match_terminology("cat", "lp")


async def test_all_catalog_scan_reads_future_catalogs_without_counts():
    repo, catalogs, _ = aws_repository(
        [{"Items": [dict(id="future", name="New", language_pair_id="other")]}], []
    )
    result = await TerminologyService(repo).list_catalogs()
    assert result["items"][0]["catalog_id"] == "future"
    assert "KeyConditionExpression" not in catalogs.calls[0]


async def test_no_catalogs_returns_success_and_foreign_catalog_is_rejected():
    class EmptyRepository(FakeRepository):
        async def catalogs_page(self, language_pair_id, limit, last_key=None):
            return [], None, 0

    assert await TerminologyService(EmptyRepository()).match_terminology(
        "anything", "lp"
    ) == dict(terms=[], total_matches=0, truncated=False)
    repo = FakeRepository([dict(id="a", name="A", language_pair_id="other")])
    with pytest.raises(TerminologyError):
        await TerminologyService(repo).match_terminology("cat", "lp", ["a"])


async def test_marks_and_non_ascii_latin_reject_word_interior():
    repo = FakeRepository(terms={"a": [term("a"), term("máy"), term("cat")]})
    result = await TerminologyService(repo).match_terminology(
        "a\u0323 máy\u0338 écat caté 猫cat猫", "lp"
    )
    assert [t["source_term"] for t in result["terms"]] == ["cat"]


async def test_empty_page_still_consumes_scanned_budget():
    repo, _, _ = aws_repository([{"Items": [], "ScannedCount": 100001}], [])
    with pytest.raises(TerminologyError, match="RESOURCE_LIMIT"):
        await TerminologyService(repo).match_terminology("cat", "lp")


async def test_catalog_gsi_foreign_language_rows_are_not_matched_but_counted():
    foreign = term("cat", "FOREIGN") | {"language_pair_id": "other"}
    service = TerminologyService(FakeRepository(terms={"a": [foreign]}))
    assert (await service.match_terminology("cat", "lp"))["terms"] == []
    with pytest.raises(TerminologyError, match="RESOURCE_LIMIT"):
        await TerminologyService(
            FakeRepository(terms={"a": [foreign]}), max_records=1
        ).match_terminology("cat", "lp")


async def test_service_timeout_stops_background_cpu_cooperatively(monkeypatch):
    import asyncio
    import time
    import src.services.terminology_matcher as matcher_module

    original = matcher_module._first_match
    visited = []

    def slow_match(*args):
        visited.append(args[1])
        time.sleep(0.01)
        return original(*args)

    monkeypatch.setattr(matcher_module, "_first_match", slow_match)
    service = TerminologyService(
        FakeRepository(terms={"a": [term(f"cat{i}") for i in range(100)]}),
        timeout_seconds=0.025,
    )
    with pytest.raises(TerminologyError, match="TIMEOUT"):
        await service.match_terminology("cat1", "lp")
    await asyncio.sleep(0.03)
    stopped_count = len(visited)
    await asyncio.sleep(0.03)
    assert len(visited) == stopped_count
    assert stopped_count < 10


async def test_cancellation_stops_background_cpu_cooperatively(monkeypatch):
    import asyncio
    import time
    import src.services.terminology_matcher as matcher_module

    visited = []

    def slow_match(*args):
        visited.append(args[1])
        time.sleep(0.01)
        return None

    monkeypatch.setattr(matcher_module, "_first_match", slow_match)
    service = TerminologyService(
        FakeRepository(terms={"a": [term(f"cat{i}") for i in range(100)]})
    )
    task = asyncio.create_task(service.match_terminology("cat1", "lp"))
    await asyncio.sleep(0.025)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.03)
    stopped_count = len(visited)
    await asyncio.sleep(0.03)
    assert len(visited) == stopped_count
    assert stopped_count < 10


async def test_real_catalog_gsi_pagination_filters_foreign_language_rows():
    foreign = term("cat", "FOREIGN") | {"language_pair_id": "other"}
    key = {"pk": "LP#other#CAT#a", "sk": "TERM#foreign"}
    repo, _, terms = aws_repository(
        [{"Items": [dict(id="a", name="A", language_pair_id="lp")]}],
        [
            {"Items": [foreign], "LastEvaluatedKey": key},
            {"Items": [term("cat", "CORRECT")]},
        ],
    )
    result = await TerminologyService(repo).match_terminology("cat", "lp")
    assert result["terms"][0]["target_term"] == "CORRECT"
    assert terms.calls[1]["ExclusiveStartKey"] == key


async def test_service_total_timeout_includes_database_wait():
    import asyncio

    class SlowRepository(FakeRepository):
        async def catalogs_page(self, *args):
            await asyncio.sleep(1)
            return [], None, 0

    with pytest.raises(TerminologyError, match="TIMEOUT"):
        await TerminologyService(
            SlowRepository(), timeout_seconds=0.01
        ).match_terminology("cat", "lp")


async def test_catalog_language_direction_resolves_actual_uuid_once_and_orphans():
    from unittest.mock import AsyncMock

    actual_id = "bf82c598-513b-4d24-b0b4-9ca7299aa261"
    catalogs = [
        dict(id=c, name=c, language_pair_id=lp)
        for c, lp in [("a", actual_id), ("b", actual_id), ("orphan", "legacy")]
    ]
    repo = FakeRepository(catalogs)
    repo.get_language_pair = AsyncMock(
        side_effect=lambda ident: (
            {"source_language": "zh", "target_language": "vi"}
            if ident == actual_id
            else None
        )
    )
    result = await TerminologyService(repo).list_catalogs()
    assert result["items"][0]["source_language"] == "zh"
    assert result["items"][1]["target_language"] == "vi"
    assert result["items"][2]["source_language"] is None
    assert result["items"][2]["target_language"] is None
    assert repo.get_language_pair.await_count == 2


async def test_repository_language_pair_get_uses_readonly_global_exact_key():
    from types import SimpleNamespace

    table = Mock()
    table.get_item.return_value = {
        "Item": dict(id="uuid", source_language="vi", target_language="en")
    }
    resource = Mock()
    resource.Table.return_value = table

    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)

    repo = TerminologyRepository(
        SimpleNamespace(_get_resource=lambda: resource, _run_sync=run)
    )
    assert (await repo.get_language_pair("uuid"))["source_language"] == "vi"
    resource.Table.assert_called_once_with("doc_translation_language_pairs")
    table.get_item.assert_called_once_with(
        Key={"pk": "USER#__global__", "sk": "LP#uuid"}
    )


async def test_catalog_language_resolution_uses_total_timeout():
    import asyncio

    class SlowLanguageRepository(FakeRepository):
        async def get_language_pair(self, language_pair_id):
            await asyncio.sleep(1)
            return {"source_language": "zh", "target_language": "vi"}

    with pytest.raises(TerminologyError, match="TIMEOUT"):
        await TerminologyService(
            SlowLanguageRepository(), timeout_seconds=0.01
        ).list_catalogs()
