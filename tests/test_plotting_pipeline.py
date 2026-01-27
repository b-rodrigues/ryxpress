"""
Tests for updated get_nodes_edges with pipeline metadata support.
"""
import json
import tempfile
from pathlib import Path


def test_get_nodes_edges_with_pipeline_metadata():
    """Test that get_nodes_edges extracts pipeline_group and pipeline_color."""
    from ryxpress.plotting import get_nodes_edges
    
    # Create a temporary dag.json with pipeline metadata
    dag_data = {
        "derivations": [
            {
                "deriv_name": ["data"],
                "depends": [],
                "type": ["rxp_py"],
                "pipeline_group": ["ETL"],
                "pipeline_color": ["#E69F00"]
            },
            {
                "deriv_name": ["model"],
                "depends": ["data"],
                "type": ["rxp_py"],
                "pipeline_group": ["Model"],
                "pipeline_color": ["#56B4E9"]
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(dag_data, f)
        temp_path = f.name
    
    try:
        result = get_nodes_edges(temp_path)
        
        nodes = result["nodes"]
        assert len(nodes) == 2
        
        # Check that pipeline metadata is present
        data_node = next(n for n in nodes if n["id"] == "data")
        model_node = next(n for n in nodes if n["id"] == "model")
        
        assert data_node["pipeline_group"] == "ETL"
        assert data_node["pipeline_color"] == "#E69F00"
        assert model_node["pipeline_group"] == "Model"
        assert model_node["pipeline_color"] == "#56B4E9"
    finally:
        Path(temp_path).unlink()


def test_get_nodes_edges_without_pipeline_metadata():
    """Test that get_nodes_edges works without pipeline metadata (backward compat)."""
    from ryxpress.plotting import get_nodes_edges
    
    # Create a dag.json without pipeline metadata
    dag_data = {
        "derivations": [
            {
                "deriv_name": ["data"],
                "depends": [],
                "type": ["rxp_py"]
            },
            {
                "deriv_name": ["model"],
                "depends": ["data"],
                "type": ["rxp_py"]
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(dag_data, f)
        temp_path = f.name
    
    try:
        result = get_nodes_edges(temp_path)
        
        nodes = result["nodes"]
        assert len(nodes) == 2
        
        # Check that default values are used
        data_node = next(n for n in nodes if n["id"] == "data")
        
        assert data_node["pipeline_group"] == "default"
        assert data_node["pipeline_color"] is None
    finally:
        Path(temp_path).unlink()


def test_rxp_phart_colors_labels(monkeypatch, tmp_path):
    from ryxpress import plotting

    dag_data = {
        "derivations": [
            {
                "deriv_name": ["alpha"],
                "depends": [],
                "type": ["rxp_py"],
                "pipeline_group": ["ETL"],
                "pipeline_color": ["#E69F00"],
            },
            {
                "deriv_name": ["beta"],
                "depends": ["alpha"],
                "type": ["rxp_py"],
                "pipeline_group": ["Model"],
                "pipeline_color": [None],
            },
        ]
    }
    dag_path = tmp_path / "dag.json"
    dag_path.write_text(json.dumps(dag_data), encoding="utf-8")

    dot_content = (
        'digraph G {\n'
        '  "alpha" [label="alpha"];\n'
        '  "beta" [label="beta"];\n'
        '  "alpha" -> "beta";\n'
        '}\n'
    )
    dot_path = tmp_path / "dag.dot"
    dot_path.write_text(dot_content, encoding="utf-8")

    original_get_nodes_edges = plotting.get_nodes_edges

    def fake_get_nodes_edges(path_dag="_rixpress/dag.json"):
        return original_get_nodes_edges(dag_path)

    monkeypatch.setattr(plotting, "get_nodes_edges", fake_get_nodes_edges)

    def fake_phart_class(graph):
        class FakeRenderer:
            def __init__(self, _graph):
                self._graph = _graph
            def render(self):
                return "rendered"
        return FakeRenderer(graph)

    class FakePydot:
        @staticmethod
        def graph_from_dot_data(data):
            expected_alpha = plotting._colorize("alpha", plotting._hex_to_ansi("#E69F00"))
            assert expected_alpha in data
            assert 'label="beta"' in data
            return [object()]

    class FakeNetworkX:
        class nx_pydot:
            @staticmethod
            def from_pydot(_graph):
                class FakeGraph:
                    def nodes(self, data=True):
                        return []
                return FakeGraph()

        @staticmethod
        def relabel_nodes(graph, mapping):
            return graph

    class FakePhart:
        ASCIIRenderer = staticmethod(fake_phart_class)

    monkeypatch.setitem(__import__("sys").modules, "phart", FakePhart)
    monkeypatch.setitem(__import__("sys").modules, "pydot", FakePydot)
    monkeypatch.setitem(__import__("sys").modules, "networkx", FakeNetworkX)

    plotting.rxp_phart(str(dot_path))
