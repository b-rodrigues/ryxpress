"""
Export pipeline DAG for CI and prepare node/edge data.

This module provides two functions translated from the original R code:

- get_nodes_edges(path_dag="_rixpress/dag.json")
    Reads the pipeline DAG JSON produced by rxp_populate and returns a dict
    with 'nodes' and 'edges' lists suitable for further processing.

- rxp_dag_for_ci(nodes_and_edges=None, output_file="_rixpress/dag.dot")
    Uses python-igraph to build a graph from the nodes/edges and writes a DOT
    file to output_file. Raises ImportError if python-igraph is not available.

Notes:
- This implementation is defensive about JSON shape: it tolerates derivation
  entries where fields may be scalars or lists, and normalizes them.
- The DOT writer expects the python 'igraph' package (python-igraph). If it is
  not importable, rxp_dag_for_ci raises ImportError with a clear message.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


def _normalize_to_list(value) -> List[str]:
    """
    Normalize a value that may be None, a scalar string, or a list/tuple of strings
    into a flat list of strings.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if v is None:
                continue
            out.append(str(v))
        return out
    # scalar -> single-element list
    return [str(value)]


def get_nodes_edges(path_dag: Union[str, Path] = "_rixpress/dag.json") -> Dict[str, List[Dict]]:
    """
    Read _rixpress/dag.json and return a dict with 'nodes' and 'edges'.

    nodes: list of {"id": <name>, "label": <name>, "group": <type>}
    edges: list of {"from": <dep>, "to": <deriv>, "arrows": "to"}

    Raises FileNotFoundError if the JSON file is missing, ValueError if the
    JSON contents don't contain derivations.
    """
    path = Path(path_dag)
    if not path.exists():
        raise FileNotFoundError("dag.json missing! Did you run 'rxp_populate()'?")

    data = json.loads(path.read_text(encoding="utf-8"))
    derivations = data.get("derivations")
    if derivations is None:
        raise ValueError("No 'derivations' key found in dag.json")

    nodes_seen = {}
    edges: List[Dict[str, str]] = []

    # derivations is expected to be a list of dict-like objects
    for entry in derivations:
        if not isinstance(entry, dict):
            continue
        # Derivation name: prefer 'deriv_name', fall back to 'name' or 'derivation'
        deriv_name = entry.get("deriv_name") or entry.get("name") or entry.get("derivation")
        if deriv_name is None:
            continue
        # type (group)
        group = None
        t = entry.get("type")
        if t is not None:
            # type might be scalar or list; normalize to first value if list
            t_list = _normalize_to_list(t)
            group = t_list[0] if t_list else None

        # Add node (deduplicated)
        id_str = str(deriv_name)
        if id_str not in nodes_seen:
            nodes_seen[id_str] = {"id": id_str, "label": id_str, "group": group}

        # dependencies: could be absent, scalar, or list
        depends = entry.get("depends")
        dep_list = _normalize_to_list(depends)
        for dep in dep_list:
            dep_str = str(dep)
            edges.append({"from": dep_str, "to": id_str, "arrows": "to"})
            # Note: we do NOT automatically create nodes for dependencies that are
            # not present as derivations in the file (mirrors R behavior).
            # If you'd like dependency-only nodes included, uncomment below:
            # if dep_str not in nodes_seen:
            #     nodes_seen[dep_str] = {"id": dep_str, "label": dep_str, "group": None}

    # Convert nodes_seen to a list preserving insertion order
    nodes = list(nodes_seen.values())

    return {"nodes": nodes, "edges": edges}


def rxp_dag_for_ci(nodes_and_edges: Optional[Dict[str, List[Dict]]] = None,
                   output_file: Union[str, Path] = "_rixpress/dag.dot") -> None:
    """
    rxp_dag_for_ci

    Build an igraph object from nodes_and_edges and write a DOT file for CI.

    - nodes_and_edges: dict with keys 'nodes' and 'edges' as returned by
      get_nodes_edges(). If None, get_nodes_edges() is called.
    - output_file: path to write DOT file. Parent directories are created as needed.

    Raises ImportError if python-igraph is not installed.
    """
    # Lazy import igraph and raise helpful error if not available
    try:
        import igraph  # python-igraph
    except Exception as e:  # ImportError or other import-time errors
        raise ImportError(
            "The python 'igraph' package is required for rxp_dag_for_ci. "
            "Install it with e.g. 'pip install python-igraph' and try again."
        ) from e

    if nodes_and_edges is None:
        nodes_and_edges = get_nodes_edges()

    edges = nodes_and_edges.get("edges", [])
    # Build a list of tuples (from, to) for igraph
    edge_tuples = [(e["from"], e["to"]) for e in edges]

    # Ensure output directory exists
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Create the graph from edge tuples. TupleList will create vertices named by
    # the unique labels encountered in the tuples.
    # If there are no edges but there are nodes, create an empty graph and add vertices.
    if edge_tuples:
        g = igraph.Graph.TupleList(edge_tuples, directed=True, vertex_name_attr="name")
    else:
        # no edges — create graph and add vertices from nodes list
        nodes = nodes_and_edges.get("nodes", [])
        vertex_names = [n["id"] for n in nodes]
        g = igraph.Graph(directed=True)
        if vertex_names:
            g.add_vertices(vertex_names)
            # set the 'name' attribute automatically when vertices are named

    # Set vertex 'label' attribute from vertex name
    # g.vs['name'] should exist; copy to 'label'
    try:
        names = g.vs["name"]
        g.vs["label"] = names
        # Attempt to remove the 'name' attribute to mirror R behavior.
        # python-igraph allows deleting vertex attributes via 'del g.vs["attr"]'.
        try:
            del g.vs["name"]
        except Exception:
            # If deletion is not supported in some igraph versions, leave it;
            # having both 'name' and 'label' is harmless for DOT output.
            logger.debug("Could not delete 'name' vertex attribute; leaving it in place.")
    except Exception:
        # If the graph has no vertices or attribute access fails, continue.
        pass

    # Write graph to DOT format
    # Use Graph.write with format="dot"
    try:
        g.write(str(out_path), format="dot")
    except Exception as e:
        raise RuntimeError(f"Failed to write DOT file to {out_path}: {e}") from e

def rxp_phart(dot_path: str) -> None:
    """
    Render a DOT graph file as an ASCII diagram using phart, showing node labels.

    This function reads a DOT file, parses it with pydot and networkx, and
    renders it in ASCII using phart. Node labels from the DOT file are used
    instead of numeric node IDs.

    Dependencies
    ------------
    - phart
    - pydot
    - networkx

    If any dependency is missing, the function will print an instruction to install it.

    Parameters
    ----------
    dot_path : str
        Path to the DOT file to render.

    Raises
    ------
    FileNotFoundError
        If the specified DOT file does not exist.
    ValueError
        If the DOT file is empty or cannot be parsed into a graph.
    """

    # Dependency checks
    missing = []
    try:
        import phart
        from phart import ASCIIRenderer
    except ImportError:
        missing.append("phart")
    try:
        import pydot
    except ImportError:
        missing.append("pydot")
    try:
        import networkx as nx
    except ImportError:
        missing.append("networkx")

    if missing:
        print(
            f"The following dependencies are required but not installed: {', '.join(missing)}"
        )
        print(f"Please add them to the execution environment.")
        return

    # Check file exists
    import os
    if not os.path.exists(dot_path):
        raise FileNotFoundError(f"DOT file not found: {dot_path}")

    # Load DOT file
    with open(dot_path) as f:
        dot_data = f.read()

    if not dot_data.strip():
        raise ValueError("DOT file is empty.")

    # Parse DOT into networkx graph
    graphs = pydot.graph_from_dot_data(dot_data)
    if not graphs:
        raise ValueError("No valid graphs found in DOT file.")

    G = nx.nx_pydot.from_pydot(graphs[0])

    # Map node keys to labels for display
    mapping = {node: data.get("label", str(node)) for node, data in G.nodes(data=True)}
    H = nx.relabel_nodes(G, mapping)

    # Render ASCII
    renderer = ASCIIRenderer(H)
    print(renderer.render())
