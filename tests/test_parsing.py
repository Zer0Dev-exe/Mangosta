from datetime import datetime, timedelta, timezone

import pymongo
import pytest

from mangosta.cli import _hoist_global_flags
from mangosta.errors import MangostaError
from mangosta.parsing import (
    action_from_atlas,
    action_to_atlas,
    classify_access_entry,
    ip_allowed,
    parse_expiry,
    parse_index_keys,
    parse_json_object,
    parse_privilege,
    parse_role,
    role_from_atlas,
    role_to_atlas,
)


def test_parse_role():
    assert parse_role("readWrite@tienda") == {"role": "readWrite", "db": "tienda"}
    assert parse_role("root") == {"role": "root", "db": "admin"}
    assert parse_role("read", "logs") == {"role": "read", "db": "logs"}
    assert parse_role("read@tienda.pedidos.2024") == {"role": "read", "db": "tienda", "collection": "pedidos.2024"}
    with pytest.raises(MangostaError):
        parse_role("@tienda")


def test_role_atlas_roundtrip():
    role = parse_role("read@tienda.pedidos")
    assert role_to_atlas(role) == {"roleName": "read", "databaseName": "tienda", "collectionName": "pedidos"}
    assert role_from_atlas(role_to_atlas(role)) == role


def test_parse_privilege():
    assert parse_privilege("tienda.pedidos:find,insert") == {
        "resource": {"db": "tienda", "collection": "pedidos"},
        "actions": ["find", "insert"],
    }
    assert parse_privilege("tienda:listCollections")["resource"] == {"db": "tienda", "collection": ""}
    with pytest.raises(MangostaError):
        parse_privilege("tienda")


def test_atlas_actions():
    assert action_to_atlas("listCollections") == "LIST_COLLECTIONS"
    assert action_to_atlas("find") == "FIND"
    assert action_from_atlas("LIST_COLLECTIONS") == "listCollections"


def test_classify_access_entry():
    assert classify_access_entry("1.2.3.4") == ("ipAddress", "1.2.3.4")
    assert classify_access_entry("10.0.0.5/24") == ("cidrBlock", "10.0.0.0/24")
    assert classify_access_entry("sg-123abc") == ("awsSecurityGroup", "sg-123abc")
    with pytest.raises(MangostaError):
        classify_access_entry("no-es-una-ip")


def test_ip_allowed():
    assert ip_allowed("10.1.2.3", ["10.0.0.0/8"])
    assert ip_allowed("1.2.3.4", ["1.2.3.4"])
    assert not ip_allowed("172.17.0.1", ["10.0.0.0/8", "1.2.3.4"])


def test_parse_expiry():
    now = datetime.now(timezone.utc)
    assert abs(parse_expiry("6h") - (now + timedelta(hours=6))) < timedelta(seconds=5)
    assert abs(parse_expiry("7d") - (now + timedelta(days=7))) < timedelta(seconds=5)
    assert parse_expiry("2030-01-02T03:04:05+00:00") == datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    with pytest.raises(MangostaError):
        parse_expiry("mañana")


def test_parse_index_keys():
    assert parse_index_keys("email:1,fecha:-1") == [("email", pymongo.ASCENDING), ("fecha", pymongo.DESCENDING)]
    assert parse_index_keys("nombre") == [("nombre", pymongo.ASCENDING)]
    assert parse_index_keys("texto:text") == [("texto", "text")]
    assert parse_index_keys('{"a": 1, "b": -1}') == [("a", 1), ("b", -1)]
    with pytest.raises(MangostaError):
        parse_index_keys("a:raro")


def test_parse_json_object_extended_json():
    flt = parse_json_object('{"_id": {"$oid": "665f1c2b9f1e4a3b2c1d0e0f"}}', "filtro")
    assert str(flt["_id"]) == "665f1c2b9f1e4a3b2c1d0e0f"
    with pytest.raises(MangostaError):
        parse_json_object("[1, 2]", "filtro")
    with pytest.raises(MangostaError):
        parse_json_object("{malo", "filtro")


def test_hoist_global_flags():
    assert _hoist_global_flags(["db", "drop", "x", "-y"]) == ["-y", "db", "drop", "x"]
    assert _hoist_global_flags(["doc", "find", "a", "b", "--json"]) == ["--json", "doc", "find", "a", "b"]
    assert _hoist_global_flags(["doc", "insert", "a", "b", "--", "-y"]) == ["doc", "insert", "a", "b", "--", "-y"]
