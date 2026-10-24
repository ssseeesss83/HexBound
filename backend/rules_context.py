"""Task-local resolution of actual frozen records, not just version labels."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import json

from .rules_identity import LEGACY_PACKAGE

_STORE = ContextVar("hexbound_rules_store", default=None)
_VIEW = ContextVar("hexbound_rules_view", default=None)
_EMBEDDED_LEGACY = None


class RulesView:
    def __init__(self, version, records, metadata):
        self.version = version
        self.COLLECTIONS = records
        for kind, rows in records.items():
            setattr(self, kind.upper().replace("-", "_"), rows)
        self.CLASS_LEVELS = {rid: {} for rid in self.CLASSES}
        self.SUBCLASS_LEVELS = {rid: {} for rid in self.SUBCLASSES}
        for row in self.LEVELS.values():
            if row.get("subclass"):
                self.SUBCLASS_LEVELS[row["subclass"]["index"]][row["level"]] = row
            else:
                self.CLASS_LEVELS[row["class"]["index"]][row["level"]] = row
        self.CLASS_CASTING_ABILITIES = {rid: row["spellcasting"]["spellcasting_ability"]["index"]
                                       for rid, row in self.CLASSES.items() if "spellcasting" in row}
        self.XP_THRESHOLDS = {int(level): value for level, value in metadata["xp_thresholds"].items()}
        self.FEATURE_BINDINGS = metadata["feature_bindings"]
        self.SPELL_EFFECTS = metadata["spell_effects"]
        self.ACTION_FEATURES = metadata["action_features"]

    def class_level(self, class_id, level):
        if isinstance(level, bool) or level not in self.CLASS_LEVELS.get(class_id, {}):
            raise ValueError("Invalid class level in pinned package")
        return deepcopy(self.CLASS_LEVELS[class_id][level])

    def lookup(self, kind, record_id):
        from .compendium import lookup
        return lookup(kind, record_id, _collections=self.COLLECTIONS)

    def get_catalog(self, *args, **kwargs):
        from .compendium import get_catalog
        return get_catalog(*args, _collections=self.COLLECTIONS, **kwargs)


@contextmanager
def active_store(store):
    token = _STORE.set(store)
    try:
        yield
    finally:
        _STORE.reset(token)


def active_version():
    view = _VIEW.get()
    if view is not None:
        return view.version
    store = _STORE.get()
    if store is not None:
        with store.connect() as db:
            row = db.execute("SELECT package_version FROM rules_activation WHERE ruleset_id='dnd5e-2014-srd5.1'").fetchone()
        if row:
            return row["package_version"]
    return LEGACY_PACKAGE


def resolve(version=None):
    global _EMBEDDED_LEGACY
    version = version or active_version()
    previous = _VIEW.get()
    if previous is not None and previous.version == version:
        return previous
    store = _STORE.get()
    if store is None:
        if version != LEGACY_PACKAGE:
            raise ValueError("Pinned rules package is unavailable: " + version)
        from .rules_packages import build_legacy_package
        if _EMBEDDED_LEGACY is None:
            package = build_legacy_package()
            _EMBEDDED_LEGACY = RulesView(version, package["records"], package)
        return _EMBEDDED_LEGACY
    # Cache only immutable installed versions. Different stores never share views.
    cache = getattr(store, "_rules_views", None)
    if cache is None:
        cache = store._rules_views = {}
    if version in cache:
        return cache[version]
    with store.connect() as db:
        row = db.execute("SELECT metadata FROM rules_packages WHERE version=?", (version,)).fetchone()
        if row is None:
            raise ValueError("Pinned rules package is unavailable: " + version)
        records = {}
        for record in db.execute("SELECT kind,id,payload FROM rules_records WHERE package_version=?", (version,)):
            records.setdefault(record["kind"], {})[record["id"]] = json.loads(record["payload"])
    view = RulesView(version, records, json.loads(row["metadata"]))
    cache[version] = view
    return view


def current_view():
    return _VIEW.get()


@contextmanager
def using_version(version=None):
    token = _VIEW.set(resolve(version))
    try:
        yield _VIEW.get()
    finally:
        _VIEW.reset(token)


def bound_rules(function):
    @wraps(function)
    def call(*args, **kwargs):
        subject = args[0] if args and isinstance(args[0], dict) else None
        version = subject.get("rules_package_version", LEGACY_PACKAGE) if subject is not None else active_version()
        with using_version(version):
            return function(*args, **kwargs)
    return call
