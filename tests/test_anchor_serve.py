"""Local serve mode: GET / serves the page, POST /save persists votes."""

import json
import threading
import urllib.request

from orq_arena.anchor import make_annotation_server


def _server(tmp_path):
    srv = make_annotation_server("<!doctype html>PAGE", tmp_path, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, payload) -> int:
    req = urllib.request.Request(
        url + "/save",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def test_get_serves_page_and_unknown_paths_404(tmp_path):
    srv, url = _server(tmp_path)
    try:
        assert urllib.request.urlopen(url + "/").read() == b"<!doctype html>PAGE"
        try:
            urllib.request.urlopen(url + "/etc/passwd")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_post_save_writes_sanitized_vote_file(tmp_path):
    srv, url = _server(tmp_path)
    try:
        status = _post(
            url,
            {
                "schema": 1,
                "seed": 42,
                "source": "x",
                "annotator": "Dana K!",
                "votes": {"k1": "A", "k2": "bogus", "k3": "tie"},
                "extra_field": "dropped",
            },
        )
        assert status == 204
        path = tmp_path / "votes-dana-k.json"
        assert path in srv.votes_written
        saved = json.loads(path.read_text())
        assert saved["votes"] == {"k1": "A", "k3": "tie"}  # bogus filtered
        assert "extra_field" not in saved
    finally:
        srv.shutdown()


def test_post_bad_json_is_400_not_crash(tmp_path):
    srv, url = _server(tmp_path)
    try:
        req = urllib.request.Request(url + "/save", data=b"not json", method="POST")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        assert not srv.votes_written
    finally:
        srv.shutdown()


def test_page_has_serve_hook():
    from orq_arena.anchor import annotation_items, render_annotate_page
    from tests.test_anchor_items import RECORDS

    page = render_annotate_page(annotation_items(RECORDS, seed=7), seed=7, source="x")
    assert "SERVED" in page and "'/save'" in page
