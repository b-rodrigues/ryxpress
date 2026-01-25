"""
Trace lineage of derivations — translation of R's rxp_trace to Python.

Behavior:

- Reads a dag.json (default: _rixpress/dag.json) and expects a top-level object
  with a "derivations" list.
- Builds dependency (depends_map) and reverse-dependency maps.
- If name is provided, prints a lineage for that derivation (ancestors and children).
- If name is None, prints an inverted global pipeline view (outputs -> inputs),
  starting from sinks (nodes with no children).
- transitive=True shows transitive closure and marks transitive-only nodes with "*".
- include_self=True includes the node itself in returned dependency lists.
- Returns a dict mapping each derivation name to {"dependencies": [...], "reverse_dependencies": [...]}.
- Raises FileNotFoundError / ValueError / RuntimeError for missing/invalid inputs.
- When color=True and derivations have pipeline_color, names are coloured in output.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union


__all__ = ["rxp_trace"]


def _hex_to_ansi(hex_color: str) -> str:
    """
    Convert a hex colour (e.g., '#E69F00') to an ANSI 24-bit escape code.
    Returns empty string if conversion fails.
    """
    if not hex_color:
        return ""
    # Remove leading #
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return ""
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except ValueError:
        return ""


def _colorize(text: str, ansi_code: str) -> str:
    """Apply ANSI colour code to text and reset afterwards."""
    if not ansi_code:
        return text
    return f"{ansi_code}{text}\033[0m"


def _supports_color() -> bool:
    """Check if the terminal supports colour output."""
    # Simple heuristic: check if stdout is a tty and NO_COLOR is not set
    import os
    if os.environ.get("NO_COLOR"):
        return False
    # Check for forced color or CI environments (like GitHub Actions)
    if os.environ.get("FORCE_COLOR") or os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        return True
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def _load_dag(path: Union[str, Path]) -> Tuple[List[dict], Dict[str, Optional[str]]]:
    """
    Load dag.json and return (derivations_list, color_map).
    
    color_map maps derivation name -> pipeline_color (or None).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Could not find dag file at: {path}. By default rxp_trace expects '_rixpress/dag.json'. If your dag.json is elsewhere, pass dag_file explicitly.")
    try:
        with p.open("r", encoding="utf-8") as fh:
            dag = json.load(fh)
    except Exception as e:
        raise RuntimeError(f"Failed to parse dag.json: {e}")
    if not isinstance(dag, dict) or "derivations" not in dag or not isinstance(dag["derivations"], list) or len(dag["derivations"]) == 0:
        raise ValueError("Invalid dag.json: no derivations found.")
    
    derivations = dag["derivations"]
    
    # Build colour map
    color_map: Dict[str, Optional[str]] = {}
    for d in derivations:
        name = _extract_name_raw(d)
        if name:
            # Extract pipeline_color (may be scalar or list)
            pc = d.get("pipeline_color")
            if isinstance(pc, list):
                pc = pc[0] if pc else None
            color_map[name] = pc if isinstance(pc, str) else None
    
    return derivations, color_map


def _extract_name_raw(d: dict) -> Optional[str]:
    """Extract name without full validation (used internally)."""
    dn = d.get("deriv_name", None)
    if dn is None:
        return None
    if isinstance(dn, (list, tuple)):
        for el in dn:
            if el is None:
                continue
            s = str(el).strip()
            if s:
                return s
        return None
    s = str(dn).strip()
    return s if s else None


def _extract_name(d: dict) -> Optional[str]:
    """
    Extract a single string name from d['deriv_name'] which may be None, a scalar,
    or a list. Mirrors the R logic: pick the first non-empty element when a list.
    Returns None if no usable name found.
    """
    dn = d.get("deriv_name", None)
    if dn is None:
        return None
    # If it's a list/sequence (but not a string), iterate
    if isinstance(dn, (list, tuple)):
        for el in dn:
            if el is None:
                continue
            s = str(el).strip()
            if s:
                return s
        return None
    # scalar: convert to string and ensure non-empty
    s = str(dn).strip()
    return s if s else None


def _unique_preserve_order(seq: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _make_depends_map(derivs: List[dict], names: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {n: [] for n in names}
    for idx, d in enumerate(derivs):
        deps = d.get("depends", None)
        if deps is None:
            dep_list: List[str] = []
        else:
            # flatten nested lists/values into strings
            flat: List[str] = []
            if isinstance(deps, (list, tuple)):
                for el in deps:
                    if el is None:
                        continue
                    # el might be nested lists; try to coerce
                    if isinstance(el, (list, tuple)):
                        for sub in el:
                            if sub is None:
                                continue
                            flat.append(str(sub))
                    else:
                        flat.append(str(el))
            else:
                flat.append(str(deps))
            # filter out empty entries and keep only internal DAG deps and drop self-loops
            dep_list = [s for s in (x.strip() for x in flat) if s and s in names and s != names[idx]]
        out[names[idx]] = _unique_preserve_order(dep_list)
    return out


def _build_reverse_map(dep_map: Dict[str, List[str]], names: List[str]) -> Dict[str, List[str]]:
    rev: Dict[str, List[str]] = {n: [] for n in names}
    for src, deps in dep_map.items():
        for dep in deps:
            rev[dep] = _unique_preserve_order(rev.get(dep, []) + [src])
    return rev


def _traverse(start: str, graph: Dict[str, List[str]]) -> List[str]:
    """
    Breadth-like traversal similar to the R implementation:
    - start with stack = graph[start]
    - repeatedly pop the first element, append to visited, and enqueue neighbours
      that are not already visited or in stack.
    Returns visited in the order discovered.
    """
    visited: List[str] = []
    stack: List[str] = list(graph.get(start, []) or [])
    while stack:
        node = stack[0]
        stack = stack[1:]
        if node in visited:
            continue
        visited.append(node)
        nb = graph.get(node) or []
        # append neighbours that are not already visited or queued
        for n in nb:
            if n not in visited and n not in stack:
                stack.append(n)
    return visited


def _marked_vec(target: str, graph: Dict[str, List[str]], transitive: bool) -> List[str]:
    imm = graph.get(target) or []
    imm_unique = _unique_preserve_order(imm)
    if not transitive:
        return imm_unique
    full = _traverse(target, graph)
    # transitive-only = elements in full that are not in imm (preserve order from 'full')
    trans_only = [x for x in full if x not in imm_unique]
    return imm_unique + [f"{t}*" for t in trans_only]


def rxp_trace(
    name: Optional[str] = None,
    dag_file: Union[str, Path] = Path("_rixpress") / "dag.json",
    transitive: bool = True,
    include_self: bool = False,
    color: bool = True,
) -> Dict[str, Dict[str, List[str]]]:
    """
    Trace lineage of derivations.

    Args:
        name: Name of the derivation to trace. If None, traces the whole pipeline.
        dag_file: Path to the dag.json file (defaults to "_rixpress/dag.json").
        transitive: If True, include transitive dependencies marked with '*'.
        include_self: If True, include the node itself in dependency lists.
        color: If True and derivations have pipeline_color, names are coloured in output.

    Returns:
        A dict mapping each inspected derivation name to a dict with keys:
        - 'dependencies' : list of dependency names (ancestors), with transitive-only names marked with '*'
        - 'reverse_dependencies' : list of reverse dependents (children), with transitive-only names marked with '*'

    Side-effect:
        Prints a tree representation to stdout (either the whole pipeline or
        the single-node lineage). When color=True and terminal supports it,
        derivation names are coloured by their pipeline_color.
    """
    derivs, color_map = _load_dag(dag_file)
    
    # Check if we should use colour
    use_color = color and _supports_color()
    
    # Helper to get coloured name
    def maybe_color(node_name: str, suffix: str = "") -> str:
        """Return node name with optional colour and suffix."""
        base_name = node_name.rstrip("*")
        star = "*" if node_name.endswith("*") else ""
        display_name = base_name + star + suffix
        
        if use_color:
            hex_color = color_map.get(base_name)
            if hex_color:
                ansi = _hex_to_ansi(hex_color)
                return _colorize(display_name, ansi)
        return display_name

    all_names: List[str] = []
    for d in derivs:
        nm = _extract_name(d)
        if nm is None:
            raise ValueError("Found derivations with missing or unparsable names in dag.json.")
        all_names.append(nm)

    if name is not None and name not in all_names:
        # mirror R's head(...) behaviour for listing available names
        snippet = ", ".join(all_names[:20])
        more = ", ..." if len(all_names) > 20 else ""
        raise ValueError(f"Derivation '{name}' not found in dag.json (available: {snippet}{more}).")

    depends_map = _make_depends_map(derivs, all_names)
    reverse_map = _build_reverse_map(depends_map, all_names)

    # helper to print single lineage (deps and reverse deps)
    def print_single(target: str) -> None:
        print(f"==== Lineage for: {maybe_color(target)} ====")
        # Dependencies (ancestors)
        print("Dependencies (ancestors):")
        visited: List[str] = []

        def rec_dep(node: str, depth: int) -> None:
            parents = depends_map.get(node) or []
            if not parents:
                if depth == 0:
                    print("  - <none>")
                return
            for p in parents:
                label = f"{p}*" if (transitive and depth >= 1) else p
                print(("  " * (depth + 1)) + "- " + maybe_color(label))
                if p not in visited:
                    visited.append(p)
                    rec_dep(p, depth + 1)

        rec_dep(target, 0)

        print("\nReverse dependencies (children):")
        visited = []

        def rec_rev(node: str, depth: int) -> None:
            kids = reverse_map.get(node) or []
            if not kids:
                if depth == 0:
                    print("  - <none>")
                return
            for k in kids:
                label = f"{k}*" if (transitive and depth >= 1) else k
                print(("  " * (depth + 1)) + "- " + maybe_color(label))
                if k not in visited:
                    visited.append(k)
                    rec_rev(k, depth + 1)

        rec_rev(target, 0)

        if transitive:
            print("\nNote: '*' marks transitive dependencies (depth >= 2).\n")

    # helper to print forest starting from given roots, using depends_map (outputs -> inputs)
    def print_forest_once(roots: List[str], graph: Dict[str, List[str]], transitive_flag: bool) -> None:
        visited_nodes: List[str] = []

        def rec(node: str, depth: int) -> None:
            label = f"{node}*" if (transitive_flag and depth >= 2) else node
            print(("  " * depth) + "- " + maybe_color(label))
            if node in visited_nodes:
                return
            visited_nodes.append(node)
            kids = graph.get(node) or []
            if not kids:
                return
            for k in kids:
                rec(k, depth + 1)

        for r in roots:
            rec(r, 0)

    # sinks: nodes with no children in reverse_map
    def sinks() -> List[str]:
        no_children = [n for n, kids in reverse_map.items() if not kids]
        if no_children:
            return no_children
        outdeg_vals = {n: len(kids) for n, kids in reverse_map.items()}
        if outdeg_vals:
            min_outdeg = min(outdeg_vals.values())
            return [n for n, v in outdeg_vals.items() if v == min_outdeg]
        return []

    # Build results mapping
    results: Dict[str, Dict[str, List[str]]] = {}
    for nm in all_names:
        deps = _marked_vec(nm, depends_map, transitive)
        rdeps = _marked_vec(nm, reverse_map, transitive)
        if include_self:
            deps = _unique_preserve_order([nm] + deps)
            rdeps = _unique_preserve_order([nm] + rdeps)
        results[nm] = {"dependencies": deps, "reverse_dependencies": rdeps}

    if name is None:
        print("==== Pipeline dependency tree (outputs \u2192 inputs) ====")
        for root in sinks():
            print_forest_once([root], depends_map, transitive)
        if transitive:
            print("\nNote: '*' marks transitive dependencies (depth >= 2).\n")
        return results
    else:
        print_single(name)
        # return only the single-name mapping to match the R invisible(results[name]) behaviour
        return {name: results[name]}
