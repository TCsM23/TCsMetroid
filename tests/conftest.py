import copy

import pytest

from app import create_app
from app.demo_map import DEMO_MAP
from app.engine.graph import WorldGraph


@pytest.fixture
def demo_dict():
    return copy.deepcopy(DEMO_MAP)


@pytest.fixture
def graph(demo_dict):
    return WorldGraph.from_dict(demo_dict)


@pytest.fixture
def vanilla(graph):
    return graph.vanilla_placement()


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "test"})


@pytest.fixture
def client(app):
    return app.test_client()
