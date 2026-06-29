"""共享 fixtures — 加载四份协议 + 协议无关引擎"""

import os
import pytest

from models.loader import load_protocol
from services.query_engine import QueryEngine
from services.can_codec import CanCodec

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _load(proto_id: str):
    path = os.path.join(DATA_DIR, f"{proto_id}.json")
    if not os.path.exists(path):
        pytest.skip(f"协议文件不存在: {path}")
    return load_protocol(path)


# ── 协议定义 fixtures ──

@pytest.fixture(scope="module")
def gbt27930():
    return _load("gbt27930_v1.1")


@pytest.fixture(scope="module")
def anshibo():
    return _load("anshibo_1k040b")


@pytest.fixture(scope="module")
def sg_unified():
    return _load("sg_unified_v107")


@pytest.fixture(scope="module")
def infypower():
    return _load("infypower_v107")


@pytest.fixture(
    scope="module",
    params=["gbt27930_v1.1", "anshibo_1k040b", "sg_unified_v107", "infypower_v107"],
)
def all_protocols(request):
    return _load(request.param)


# ── 引擎 fixtures ──

@pytest.fixture(scope="module")
def gbt27930_engine(gbt27930):
    return QueryEngine(gbt27930), CanCodec(gbt27930)


@pytest.fixture(scope="module")
def anshibo_engine(anshibo):
    return QueryEngine(anshibo), CanCodec(anshibo)


@pytest.fixture(scope="module")
def sg_unified_engine(sg_unified):
    return QueryEngine(sg_unified), CanCodec(sg_unified)


@pytest.fixture(scope="module")
def infypower_engine(infypower):
    return QueryEngine(infypower), CanCodec(infypower)
