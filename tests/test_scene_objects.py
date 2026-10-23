from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.schemas import SceneObject, ScenarioNode, parse_card
from backend.dm import GeneratedScene
from backend.content import SCENES
from backend.studio import seed_items


def obj(**changes):
    return {"id": "cabinet", "name": "铁柜", "tags": ["movable", "cover"], **changes}


def node(**changes):
    return {"id": "room", "title": "室内", "text": "铁柜靠着墙。", "ending": True, **changes}


def generated(**changes):
    return {"title": "室内", "text": "铁柜靠着墙。", "objective": "寻找道路", "actions": [
        {"id": "investigate", "label": "调查", "ability": "int", "dc": 12},
        {"id": "parley", "label": "交涉", "ability": "cha", "dc": 10}], **changes}


def test_objects_defaults_and_legacy_absence():
    assert SceneObject.model_validate(obj()).hp == 10
    assert SceneObject.model_validate(obj()).dc == 12
    assert ScenarioNode.model_validate(node()).objects == []
    assert GeneratedScene.model_validate(generated()).objects == []


@pytest.mark.parametrize("changes", [dict(hp=0), dict(hp=101), dict(hp="10"), dict(hp=True), dict(dc=4), dict(dc=26), dict(tags=["execute"]), dict(tags=["fire", "fire"]), dict(script="print(1)"), dict(id="bad space")])
def test_objects_reject_invalid_or_executable_data(changes):
    with pytest.raises(ValidationError):
        SceneObject.model_validate(obj(**changes))


@pytest.mark.parametrize("model,base", [(ScenarioNode,node), (GeneratedScene,generated)])
def test_scene_object_ids_unique_and_bounded(model, base):
    for objects in ([obj(), obj()], [obj(id=f"obj-{i}") for i in range(21)]):
        with pytest.raises(ValidationError):
            model.model_validate(base(objects=objects))
    assert len(model.model_validate(base(objects=[obj(id=f"obj-{i}") for i in range(20)])).objects) == 20


def test_authored_presets_validate_and_have_grounded_objects():
    for scene in SCENES:
        assert scene["objects"]
        for item in scene["objects"]:
            SceneObject.model_validate(item)
    books = [parse_card(kind, card) for kind,card in seed_items() if kind == "scenario"]
    customs = next(n for n in books[0]["nodes"] if n["id"] == "customs")
    assert {"movable", "cover"} <= set(customs["objects"][0]["tags"])
    old = deepcopy(customs)
    old.pop("objects")
    assert ScenarioNode.model_validate(old).objects == []
