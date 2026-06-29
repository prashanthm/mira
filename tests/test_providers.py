import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mira.providers.jsonl import JsonlProvider


def _write(tmp, name, rows):
    p = os.path.join(tmp, name)
    with open(p, "w") as f:
        if name.endswith(".json"):
            json.dump(rows, f)
        else:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return p


def test_jsonl_reads_lines_and_limits(tmp_path):
    d = str(tmp_path)
    _write(d, "grades.jsonl", [{"i": i} for i in range(10)])
    prov = JsonlProvider("sentinel", {"grades": "grades.jsonl"}, base_dir=d)
    rows = prov.read("grades", limit=3)
    assert [r["i"] for r in rows] == [7, 8, 9]
    assert prov.name() == "sentinel"
    assert prov.resources() == ["grades"]


def test_json_object_resource(tmp_path):
    d = str(tmp_path)
    _write(d, "scorecard.json", {"overall": {"x": 1}})
    prov = JsonlProvider("s", {"scorecard": "scorecard.json"}, base_dir=d)
    assert prov.read("scorecard")["overall"]["x"] == 1


def test_missing_file_is_empty(tmp_path):
    prov = JsonlProvider("s", {"grades": "nope.jsonl"}, base_dir=str(tmp_path))
    assert prov.read("grades") == []


def test_unknown_resource_raises(tmp_path):
    prov = JsonlProvider("s", {"grades": "g.jsonl"}, base_dir=str(tmp_path))
    try:
        prov.read("missing")
        assert False, "expected KeyError"
    except KeyError:
        pass
