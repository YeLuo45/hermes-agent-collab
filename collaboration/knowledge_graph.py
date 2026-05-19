"""
Knowledge Graph for hermes-agent-collab.
Supports entity-relationship modeling, Cypher-like queries, and visualization export.
"""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class KGNode:
    """A node in the knowledge graph."""
    id: str
    labels: list[str]  # e.g., ["Agent", "Task", "Template"]
    properties: dict = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KGRelationship:
    """A relationship between two nodes in the knowledge graph."""
    id: str
    type: str  # e.g., "DEPENDS_ON", "BELONGS_TO", "COLLABORATES_WITH"
    source_id: str
    target_id: str
    properties: dict = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cypher-like Query Parser
# ---------------------------------------------------------------------------

class CypherParser:
    """
    Simple Cypher-like query parser supporting:
    - MATCH (n:Label) RETURN n
    - MATCH (n:Label {prop: 'value'}) RETURN n
    - MATCH (n:Label)-[r:REL_TYPE]->(m:Label2) RETURN n, r, m
    - MATCH (n) WHERE n.prop = 'value' RETURN n
    - MATCH (n) WHERE n.prop > 10 RETURN n
    """

    LABEL_PATTERN = r'\([a-zA-Z_][a-zA-Z0-9_]*:[a-zA-Z_][a-zA-Z0-9_]*\]'
    ANON_PATTERN = r'\([a-zA-Z_][a-zA-Z0-9_]*\)\[([a-zA-Z_][a-zA-Z0-9_]*):([a-zA-Z_][a-zA-Z0-9_]*)\]\->\('

    def parse(self, query: str) -> dict:
        """Parse a Cypher-like query and return structured representation."""
        query = query.strip()
        if not query:
            raise ValueError("Empty query")

        # Detect query type
        upper_q = query.upper()

        if upper_q.startswith("MATCH"):
            return self._parse_match(query)
        elif upper_q.startswith("CREATE"):
            return self._parse_create(query)
        elif upper_q.startswith("DELETE"):
            return self._parse_delete(query)
        else:
            raise ValueError(f"Unsupported query type: {query.split()[0]}")

    def _parse_match(self, query: str) -> dict:
        """Parse MATCH query."""
        result = {"type": "MATCH", "pattern": [], "where": None, "return": [], "variables": {}}

        # Extract RETURN clause
        return_match = re.search(r'\bRETURN\b\s+(.+)', query, re.IGNORECASE)
        if return_match:
            return_items = return_match.group(1).strip()
            result["return"] = [x.strip() for x in return_items.split(',')]

        # Extract WHERE clause
        where_match = re.search(r'\bWHERE\b\s+(.+?)(?:\bRETURN\b|$)', query, re.IGNORECASE)
        if where_match:
            result["where"] = where_match.group(1).strip()

        # Parse patterns: (n:Label) or (n:Label)-->(m:Label2) etc.
        # Find all node patterns
        node_pattern = r'\(([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?\)'
        for m in re.finditer(node_pattern, query):
            var_name = m.group(1)
            label = m.group(2)[1:] if m.group(2) else None  # Remove leading ':'
            node_info = {"variable": var_name, "label": label, "properties": {}}

            # Extract inline properties: {prop: 'value'}
            props_match = re.search(r'\{([^}]*)\}', query[m.start():m.end()+20])
            if props_match:
                node_info["properties"] = self._parse_properties(props_match.group(1))

            result["variables"][var_name] = node_info

        # Parse relationship patterns
        rel_pattern = r'\[([a-zA-Z_][a-zA-Z0-9_]*)?(?::([a-zA-Z_][a-zA-Z0-9_]*))?\]'
        for m in re.finditer(rel_pattern, query):
            var_name = m.group(1) or "_rel"
            rel_type = m.group(2)
            result["pattern"].append({
                "variable": var_name,
                "type": rel_type,
                "direction": "outgoing" if "-->" in query[m.start()-3:m.start()] or "<--" in query[m.start():m.start()+3] else "incoming"
            })

        return result

    def _parse_create(self, query: str) -> dict:
        """Parse CREATE query."""
        # CREATE (n:Label {props}) RETURN n
        node_pattern = r'\(([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?(?:\s*\{([^}]*)\})?\)'
        match = re.search(node_pattern, query)
        if match:
            return {
                "type": "CREATE_NODE",
                "variable": match.group(1),
                "label": match.group(2)[1:] if match.group(2) else None,
                "properties": self._parse_properties(match.group(3) or ""),
            }
        raise ValueError(f"Cannot parse CREATE: {query}")

    def _parse_delete(self, query: str) -> dict:
        """Parse DELETE query."""
        var_match = re.search(r'\bDELETE\b\s+([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE)
        if var_match:
            return {"type": "DELETE", "variable": var_match.group(1)}
        raise ValueError(f"Cannot parse DELETE: {query}")

    def _parse_properties(self, prop_str: str) -> dict:
        """Parse {key: 'value', num: 123} style properties."""
        props = {}
        if not prop_str.strip():
            return props
        # Simple parser for key: value pairs
        pairs = re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([^\,]+)', prop_str)
        for key, value in pairs:
            value = value.strip().strip("'\"")
            # Try to parse as number
            try:
                if '.' in value:
                    props[key] = float(value)
                else:
                    props[key] = int(value)
            except ValueError:
                props[key] = value
        return props


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """
    In-memory knowledge graph with Cypher-like query support.
    Supports node/relationship CRUD, traversal, and visualization export.
    """

    RELATIONSHIP_TYPES = {
        "DEPENDS_ON", "BELONGS_TO", "COLLABORATES_WITH", "USES",
        "DEFINED_BY", "INSTANCE_OF", "AUTHORED_BY", "MEMBER_OF",
        "TRIGGERS", "CONNECTS_TO",
    }

    def __init__(self):
        self._nodes: dict[str, KGNode] = {}
        self._relationships: dict[str, KGRelationship] = {}
        # Indexes for fast lookup
        self._label_index: dict[str, set[str]] = {}  # label -> set of node_ids
        self._outgoing: dict[str, dict[str, set[str]]] = {}  # node_id -> rel_type -> set of target_ids
        self._incoming: dict[str, dict[str, set[str]]] = {}  # node_id -> rel_type -> set of source_ids
        self._parser = CypherParser()

    def add_node(self, node: KGNode) -> bool:
        """Add a node to the graph."""
        if node.id in self._nodes:
            return False  # Already exists

        self._nodes[node.id] = node

        # Update label index
        for label in node.labels:
            if label not in self._label_index:
                self._label_index[label] = set()
            self._label_index[label].add(node.id)

        # Initialize indexes
        self._outgoing[node.id] = {}
        self._incoming[node.id] = {}

        return True

    def update_node(self, node_id: str, properties: dict) -> bool:
        """Update node properties."""
        node = self._nodes.get(node_id)
        if node is None:
            return False
        node.properties.update(properties)
        return True

    def add_relationship(self, rel: KGRelationship) -> bool:
        """Add a relationship between two nodes."""
        if rel.id in self._relationships:
            return False
        if rel.source_id not in self._nodes:
            raise ValueError(f"Source node '{rel.source_id}' does not exist")
        if rel.target_id not in self._nodes:
            raise ValueError(f"Target node '{rel.target_id}' does not exist")

        self._relationships[rel.id] = rel

        # Update outgoing index
        if rel.type not in self._outgoing[rel.source_id]:
            self._outgoing[rel.source_id][rel.type] = set()
        self._outgoing[rel.source_id][rel.type].add(rel.target_id)

        # Update incoming index
        if rel.type not in self._incoming[rel.target_id]:
            self._incoming[rel.target_id][rel.type] = set()
        self._incoming[rel.target_id][rel.type].add(rel.source_id)

        return True

    def get_node(self, node_id: str) -> KGNode | None:
        """Get node by ID."""
        return self._nodes.get(node_id)

    def get_nodes_by_label(self, label: str) -> list[KGNode]:
        """Get all nodes with a specific label."""
        node_ids = self._label_index.get(label, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_relationship(self, rel_id: str) -> KGRelationship | None:
        """Get relationship by ID."""
        return self._relationships.get(rel_id)

    def get_neighbors(
        self,
        node_id: str,
        rel_type: str | None = None,
        direction: str = "outgoing",
    ) -> list[KGNode]:
        """Get neighboring nodes. direction: 'outgoing', 'incoming', or 'both'."""
        if node_id not in self._nodes:
            return []

        neighbors = []
        if direction in ("outgoing", "both"):
            index = self._outgoing.get(node_id, {})
            for rtype, target_ids in index.items():
                if rel_type is None or rtype == rel_type:
                    for tid in target_ids:
                        if tid in self._nodes:
                            neighbors.append(self._nodes[tid])

        if direction in ("incoming", "both"):
            index = self._incoming.get(node_id, {})
            for rtype, source_ids in index.items():
                if rel_type is None or rtype == rel_type:
                    for sid in source_ids:
                        if sid in self._nodes:
                            neighbors.append(self._nodes[sid])

        return neighbors

    def get_relationships(
        self,
        node_id: str,
        rel_type: str | None = None,
        direction: str = "outgoing",
    ) -> list[KGRelationship]:
        """Get relationships for a node."""
        rels = []
        for rel in self._relationships.values():
            match = False
            if direction in ("outgoing", "both") and rel.source_id == node_id:
                match = True
            if direction in ("incoming", "both") and rel.target_id == node_id:
                match = True
            if match and (rel_type is None or rel.type == rel_type):
                rels.append(rel)
        return rels

    def query(self, cypher: str) -> list[dict]:
        """Execute Cypher-like query and return results."""
        parsed = self._parser.parse(cypher)
        query_type = parsed.get("type", "")

        if query_type == "MATCH":
            return self._execute_match(parsed)
        elif query_type == "CREATE_NODE":
            return self._execute_create_node(parsed)
        elif query_type == "DELETE":
            return self._execute_delete(parsed)

        return []

    def _execute_match(self, parsed: dict) -> list[dict]:
        """Execute a parsed MATCH query."""
        results = []
        variables = parsed.get("variables", {})
        return_items = parsed.get("return", ["*"])
        where_clause = parsed.get("where")

        # Determine which label(s) to match
        matched_nodes: list[KGNode] = []

        if variables:
            # Use the first variable as the primary match
            first_var = next(iter(variables.values()))
            label = first_var.get("label")
            if label:
                matched_nodes = self.get_nodes_by_label(label)
            else:
                matched_nodes = list(self._nodes.values())
        else:
            matched_nodes = list(self._nodes.values())

        # Apply WHERE filter
        if where_clause:
            matched_nodes = self._apply_where(matched_nodes, where_clause)

        # Apply property filter from pattern
        if variables:
            first_var = next(iter(variables.values()))
            pattern_props = first_var.get("properties", {})
            if pattern_props:
                matched_nodes = [
                    n for n in matched_nodes
                    if all(n.properties.get(k) == v for k, v in pattern_props.items())
                ]

        # Build result
        if return_items == ["*"]:
            return [n.to_dict() for n in matched_nodes]

        result_rows = []
        for node in matched_nodes:
            row = {}
            for var_name, var_info in variables.items():
                if var_info.get("label") is None or node.id in self._get_ids_for_label(var_info["label"]):
                    row[var_name] = node.to_dict()
            if row:
                result_rows.append(row)

        return result_rows

    def _apply_where(self, nodes: list[KGNode], where_clause: str) -> list[KGNode]:
        """Apply WHERE clause filter to nodes."""
        # Support: n.prop = 'value', n.prop > 10, n.prop CONTAINS 'text'
        eq_match = re.search(r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^\s<>=]+)', where_clause)
        gt_match = re.search(r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s*>\s*([^\s<>=]+)', where_clause)
        lt_match = re.search(r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s*<\s*([^\s<>=]+)', where_clause)
        contains_match = re.search(r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s+CONTAINS\s+([^\s<>=]+)', where_clause, re.IGNORECASE)

        if eq_match:
            prop_name = eq_match.group(1)
            prop_val = eq_match.group(2).strip().strip("'\"")
            return [n for n in nodes if n.properties.get(prop_name) == prop_val]

        if gt_match:
            prop_name = gt_match.group(1)
            prop_val = float(gt_match.group(2).strip())
            return [n for n in nodes if isinstance(n.properties.get(prop_name), (int, float)) and n.properties.get(prop_name) > prop_val]

        if lt_match:
            prop_name = lt_match.group(1)
            prop_val = float(lt_match.group(2).strip())
            return [n for n in nodes if isinstance(n.properties.get(prop_name), (int, float)) and n.properties.get(prop_name) < prop_val]

        if contains_match:
            prop_name = contains_match.group(1)
            prop_val = contains_match.group(2).strip().strip("'\"")
            return [n for n in nodes if isinstance(n.properties.get(prop_name), str) and prop_val in n.properties.get(prop_name, "")]

        return nodes

    def _get_ids_for_label(self, label: str) -> set[str]:
        """Get all node IDs for a given label."""
        return self._label_index.get(label, set())

    def _execute_create_node(self, parsed: dict) -> list[dict]:
        """Execute CREATE NODE."""
        node_id = str(uuid.uuid4())[:8]
        node = KGNode(
            id=node_id,
            labels=[parsed["label"]] if parsed.get("label") else [],
            properties=parsed.get("properties", {}),
        )
        self.add_node(node)
        return [node.to_dict()]

    def _execute_delete(self, parsed: dict) -> list[dict]:
        """Execute DELETE node."""
        var_name = parsed.get("variable")
        # Find node by variable name pattern
        # In practice, we'd need to track variable bindings from previous query
        return [{"deleted": 0}]

    def traverse(self, start_id: str, depth: int = 3, direction: str = "both") -> list[dict]:
        """
        BFS traversal from a start node.
        Returns list of {node, distance, path} dicts.
        """
        if start_id not in self._nodes:
            return []

        visited = {start_id}
        queue = [(start_id, 0, [start_id])]
        results = []

        while queue:
            current_id, dist, path = queue.pop(0)
            if dist > depth:
                continue

            current_node = self._nodes.get(current_id)
            if current_node and dist > 0:  # Exclude start node from results
                results.append({
                    "node": current_node.to_dict(),
                    "distance": dist,
                    "path": path,
                })

            # Get neighbors
            for neighbor in self.get_neighbors(current_id, direction=direction):
                if neighbor.id not in visited:
                    visited.add(neighbor.id)
                    queue.append((neighbor.id, dist + 1, path + [neighbor.id]))

        return results

    def find_paths(self, source_id: str, target_id: str, max_depth: int = 5) -> list[list[str]]:
        """Find all paths between two nodes up to max_depth."""
        if source_id not in self._nodes or target_id not in self._nodes:
            return []

        results = []

        def dfs(current: str, target: str, path: list[str], visited: set[str]):
            if current == target:
                results.append(path[:])
                return
            if len(path) > max_depth:
                return

            for neighbor in self.get_neighbors(current, direction="both"):
                if neighbor.id not in visited:
                    visited.add(neighbor.id)
                    path.append(neighbor.id)
                    dfs(neighbor.id, target, path, visited)
                    path.pop()
                    visited.remove(neighbor.id)

        visited = {source_id}
        dfs(source_id, target_id, [source_id], visited)
        return results

    def to_cytoscape(self) -> dict:
        """
        Export graph as Cytoscape.js JSON format.
        {
            "nodes": [{"data": {"id": "...", "label": "...", ...properties}}],
            "edges": [{"data": {"id": "...", "source": "...", "target": "...", "type": "..."}}]
        }
        """
        nodes = []
        for node in self._nodes.values():
            node_data = {
                "id": node.id,
                "label": f"{node.labels[0]}: {node.id}" if node.labels else node.id,
            }
            node_data.update(node.properties)
            # Add labels as separate field
            node_data["labels"] = ",".join(node.labels)
            nodes.append({"data": node_data})

        edges = []
        for rel in self._relationships.values():
            edge_data = {
                "id": rel.id,
                "source": rel.source_id,
                "target": rel.target_id,
                "type": rel.type,
            }
            edge_data.update(rel.properties)
            edges.append({"data": edge_data})

        return {"nodes": nodes, "edges": edges}

    def to_graphviz(self) -> str:
        """Export graph as Graphviz DOT format."""
        lines = ["digraph {"]
        lines.append("  // Nodes")
        for node in self._nodes.values():
            label = "\\n".join([node.id] + node.labels)
            props = " ".join(f'{k}="{v}"' for k, v in list(node.properties.items())[:3])
            lines.append(f'  "{node.id}" [label="{label}" {props}];')
        lines.append("  // Edges")
        for rel in self._relationships.values():
            lines.append(f'  "{rel.source_id}" -> "{rel.target_id}" [label="{rel.type}"];')
        lines.append("}")
        return "\n".join(lines)

    def to_d3_json(self) -> dict:
        """
        Export as D3.js force-directed graph JSON.
        {nodes: [...], links: [...]}
        """
        nodes = []
        for node in self._nodes.values():
            n = {"id": node.id, "labels": node.labels[:]}
            n.update(node.properties)
            nodes.append(n)

        links = []
        for rel in self._relationships.values():
            links.append({
                "id": rel.id,
                "source": rel.source_id,
                "target": rel.target_id,
                "type": rel.type,
            })

        return {"nodes": nodes, "links": links}

    def stats(self) -> dict:
        """Return graph statistics."""
        label_counts = {label: len(ids) for label, ids in self._label_index.items()}
        rel_type_counts: dict[str, int] = {}
        for rel in self._relationships.values():
            rel_type_counts[rel.type] = rel_type_counts.get(rel.type, 0) + 1

        return {
            "total_nodes": len(self._nodes),
            "total_relationships": len(self._relationships),
            "label_distribution": label_counts,
            "relationship_type_distribution": rel_type_counts,
        }

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its relationships."""
        if node_id not in self._nodes:
            return False

        # Remove from label index
        for label in self._nodes[node_id].labels:
            if label in self._label_index:
                self._label_index[label].discard(node_id)

        # Remove all relationships involving this node
        to_delete = [
            rid for rid, rel in self._relationships.items()
            if rel.source_id == node_id or rel.target_id == node_id
        ]
        for rid in to_delete:
            del self._relationships[rid]

        # Remove from indexes
        if node_id in self._outgoing:
            del self._outgoing[node_id]
        if node_id in self._incoming:
            del self._incoming[node_id]

        del self._nodes[node_id]
        return True

    def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship."""
        rel = self._relationships.get(rel_id)
        if rel is None:
            return False

        # Remove from indexes
        if rel.type in self._outgoing.get(rel.source_id, {}):
            self._outgoing[rel.source_id][rel.type].discard(rel.target_id)
        if rel.type in self._incoming.get(rel.target_id, {}):
            self._incoming[rel.target_id][rel.type].discard(rel.source_id)

        del self._relationships[rel_id]
        return True
