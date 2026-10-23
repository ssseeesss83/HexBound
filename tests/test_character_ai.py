import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from backend import character_ai, character_builds, characters


class FakeDM:
    configured = True

    def __init__(self, response):
        self.response = response

    async def _complete(self, *args, **kwargs):
        return json.dumps(self.response, ensure_ascii=False)


def run(build, response=None, level=1, prompt=""):
    dm = FakeDM(response) if response is not None else SimpleNamespace(configured=False)
    return asyncio.run(character_ai.suggest(dm, build, level, prompt))


@pytest.mark.parametrize("cls", characters.CLASS_NAMES)
def test_local_all_classes_are_legal_reviewable_drafts(cls):
    result = run({"class_id": cls})
    assert result["source"] == "local"
    assert character_builds.build_preview(result["build"])["ready"]
    assert "ready" not in result
    assert "未配置AI" in "".join(result["notes"])


def test_preserves_user_fields_and_level_history_without_mutation():
    build = {"class_id": "fighter", "name": "阿雨", "profile": {"appearance": "红发"}, "abilities": {"str": 16}, "levels": [{"choices": {}}]}
    before = deepcopy(build)
    result = run(build, {"name": "蓝风", "profile": {"appearance": "蓝发", "background": "寻找家人"}, "abilities": {"str": 20}}, 2)
    assert build == before
    assert result["source"] == "llm"
    assert result["build"]["name"] == "阿雨"
    assert result["build"]["abilities"]["str"] == 16
    assert result["build"]["profile"]["appearance"] == "红发"
    assert result["build"]["profile"]["background"] == "寻找家人"
    assert result["build"]["levels"] == build["levels"]


def test_explicit_scoped_rewrite():
    result = run({"class_id": "rogue", "name": "原名", "profile": {"appearance": "红发", "background": "原背景"}}, {"name": "新名", "profile": {"appearance": "蓝发", "background": "新背景"}}, prompt="重写外貌")
    assert result["build"]["profile"]["appearance"] == "蓝发"
    assert result["build"]["profile"]["background"] == "原背景"
    assert result["build"]["name"] == "原名"


@pytest.mark.parametrize("response", [{"hp": 999}, {"class_id": "wizard"}, {"levels": []}, {"choices": {"gold": 20}}, {"abilities": {"str": 21}}, {"choices": {"skills": ["arcana"]}}, {"profile": {"background": "a"*3001}}])
def test_bad_model_output_falls_back(response):
    result = run({"class_id": "fighter"}, response)
    assert result["source"] == "fallback"
    assert character_builds.build_preview(result["build"])["ready"]


@pytest.mark.parametrize("build", [{"class_id": "fighter", "hp": 99}, {"class_id": "fighter", "choices": {"gold": 3}}, {"class_id": "fighter", "abilities": {"str": True}}, {"class_id": "fighter", "levels": [{"choices": {}, "xp": 4}]}])
def test_input_injection_rejected(build):
    with pytest.raises(ValueError):
        run(build, level=2)


@pytest.mark.parametrize("level", [0, 21, True, 1.0])
def test_level_bounds(level):
    with pytest.raises(ValueError):
        run({"class_id": "fighter"}, level=level)


def test_higher_level_remains_incomplete():
    result = run({"class_id": "wizard", "levels": []}, level=5)
    assert result["build"]["levels"] == []
    assert not character_builds.build_preview(result["build"], 5)["ready"]
    assert "尚未完成" in "".join(result["notes"])


def test_invalid_existing_choice_preserved_and_not_claimed_ready():
    result = run({"class_id": "fighter", "choices": {"skills": ["arcana"]}})
    assert result["build"]["choices"]["skills"] == ["arcana"]
    assert "尚未通过" in "".join(result["notes"])
