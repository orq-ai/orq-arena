"""The annotation page must be blind and self-contained."""

from orq_arena.anchor import annotation_items, render_annotate_page
from tests.test_anchor_items import RECORDS  # same synthetic records


def _page() -> str:
    items = annotation_items(RECORDS, seed=7)
    return render_annotate_page(items, seed=7, source="battles.jsonl")


def test_page_is_blind():
    page = _page()
    assert "model-one" not in page and "model-two" not in page
    assert "majority_verdict" not in page and "judge" not in page.lower()


def test_page_is_self_contained_and_complete():
    page = _page()
    assert page.startswith("<!doctype html>")
    for token in ("http://", "https://", "src=", "@import"):
        assert token not in page  # no external assets, no CDN
    assert "answer a 0" in page and "votes.json" in page
    assert '"seed": 7' in page or '"seed":7' in page


def test_page_embeds_all_items_once():
    page = _page()
    for rec_text in (f"prompt {i}" for i in range(6)):
        assert page.count(rec_text) == 1


def test_page_has_intro_annotate_and_done_views():
    page = _page()
    for view_id in ("view-intro", "view-annotate", "view-done"):
        assert page.count(f'id="{view_id}"') == 1
    assert "Guidelines" in page and "Download votes.json" in page
    assert "Accuracy and correctness" in page  # default criteria reach the rater
