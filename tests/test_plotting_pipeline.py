"""
Tests for updated get_nodes_edges with pipeline metadata support.
"""
import pytest
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


def test_rxp_phart_by_pipeline_colors_labels(monkeypatch, tmp_path):
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

    def fake_supports_color():
        return True

    def fake_rxp_phart(path):
        rendered = Path(path).read_text(encoding="utf-8")
        assert "\033[38;2;230;159;0malpha\033[0m" in rendered
        assert 'label="beta"' in rendered

    monkeypatch.setattr(plotting, "get_nodes_edges", fake_get_nodes_edges)
    monkeypatch.setattr(plotting, "_supports_color", fake_supports_color)
    monkeypatch.setattr(plotting, "rxp_phart", fake_rxp_phart)

    plotting.rxp_phart_by_pipeline(str(dot_path))
