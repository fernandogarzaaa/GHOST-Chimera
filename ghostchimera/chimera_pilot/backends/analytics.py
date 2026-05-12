"""Analytics backend for Chimera Pilot — Track 4: Data & Intelligence.

Provides a zero-dependency, stdlib-only analytics engine suitable for:

* RAG systems over proprietary or multi-source data
* AI-powered data pipelines and validation
* Analytics agents for natural language querying
* Anomaly detection and forecasting
* Knowledge graph extraction from documents

Design
------
The :class:`AnalyticsBackend` handles two task kinds:

``ANALYTICS_QUERY``
    Natural-language query over a provided dataset or schema.  Supports
    aggregation (count, mean, max, min, sum), filtering, grouping, and
    basic forecasting via linear regression.

``DATA_PIPELINE``
    Validate, transform, and profile a data batch.  Returns statistics,
    schema inference, null counts, and anomaly flags.

Both modes are deterministic and operate entirely in memory using stdlib
``statistics`` and ``math`` — no pandas, numpy, or other third-party libraries
required.

Usage (via Chimera Pilot)::

    task = TaskSpec.create(
        kind=TaskKind.ANALYTICS_QUERY,
        objective="count records per region",
        inputs={
            "query": "count records per region",
            "data": [
                {"region": "EU", "revenue": 1200, "q": 1},
                {"region": "US", "revenue": 3400, "q": 1},
                {"region": "EU", "revenue": 1500, "q": 2},
            ],
        },
    )

    task = TaskSpec.create(
        kind=TaskKind.DATA_PIPELINE,
        objective="validate and profile the sales dataset",
        inputs={
            "data": [...],
            "schema": {"revenue": "float", "region": "str", "q": "int"},
            "pipeline": ["validate_schema", "profile", "detect_anomalies"],
        },
    )
"""

from __future__ import annotations

import contextlib
import re
import statistics
from collections import Counter
from typing import Any

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("analytics_backend")


# ---------------------------------------------------------------------------
# Analytics engine
# ---------------------------------------------------------------------------


def _parse_nl_query(query: str, columns: list[str]) -> dict[str, Any]:
    """Translate a simple natural-language query into a structured operation dict.

    Handles patterns like:
    - "count records"
    - "average revenue"
    - "sum sales by region"
    - "max temperature"
    - "forecast revenue for next 3 quarters"
    - "detect anomalies in latency"
    """
    lower = query.strip().lower()

    # aggregation keywords
    agg_map = {
        "count": "count",
        "average": "mean",
        "mean": "mean",
        "avg": "mean",
        "sum": "sum",
        "total": "sum",
        "max": "max",
        "maximum": "max",
        "min": "min",
        "minimum": "min",
    }

    op: dict[str, Any] = {"operation": "count", "column": None, "group_by": None, "filter": None}

    # detect forecast
    if "forecast" in lower or "predict" in lower:
        op["operation"] = "forecast"
        horizon_match = re.search(r"(\d+)\s*(?:quarter|month|period|step|week|day)", lower)
        op["horizon"] = int(horizon_match.group(1)) if horizon_match else 3
        for col in columns:
            if col in lower:
                op["column"] = col
                break
        return op

    # detect anomaly detection
    if "anomal" in lower or "outlier" in lower:
        op["operation"] = "anomaly_detection"
        for col in columns:
            if col in lower:
                op["column"] = col
                break
        return op

    # detect standard aggregation
    for kw, agg in agg_map.items():
        if lower.startswith(kw) or f" {kw} " in f" {lower} ":
            op["operation"] = agg
            break

    # detect column from query
    for col in sorted(columns, key=len, reverse=True):
        if col.lower() in lower:
            op["column"] = col
            break

    # detect grouping
    group_match = re.search(r"\bby\s+(\w+)", lower)
    if group_match:
        candidate = group_match.group(1)
        # fuzzy match to known columns
        for col in columns:
            if col.lower() == candidate or candidate in col.lower():
                op["group_by"] = col
                break

    # detect simple equality filter: "where region = EU"
    filter_match = re.search(r"\bwhere\s+(\w+)\s*[=:]\s*(\S+)", lower)
    if filter_match:
        op["filter"] = {"column": filter_match.group(1), "value": filter_match.group(2).strip("'\")")}

    return op


def _apply_aggregation(
    data: list[dict[str, Any]],
    operation: str,
    column: str | None,
    group_by: str | None,
    row_filter: dict[str, Any] | None,
) -> Any:
    """Apply an aggregation operation to *data*."""
    rows = list(data)

    # apply filter
    if row_filter:
        fcol = row_filter.get("column", "")
        fval = str(row_filter.get("value", ""))
        rows = [r for r in rows if str(r.get(fcol, "")).lower() == fval.lower()]

    if operation == "count" and not group_by:
        return {"count": len(rows)}

    if operation == "count" and group_by:
        groups: Counter = Counter(str(r.get(group_by, "")) for r in rows)
        return {k: {"count": v} for k, v in sorted(groups.items())}

    if column is None:
        return {"error": "No column identified for aggregation"}

    def extract(r: dict[str, Any]) -> float | None:
        v = r.get(column)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    if group_by:
        grouped: dict[str, list[float]] = {}
        for r in rows:
            key = str(r.get(group_by, ""))
            val = extract(r)
            if val is not None:
                grouped.setdefault(key, []).append(val)
        result_dict: dict[str, Any] = {}
        for k, vals in sorted(grouped.items()):
            result_dict[k] = {operation: _agg(vals, operation)}
        return result_dict

    values = [v for r in rows if (v := extract(r)) is not None]
    if not values:
        return {"error": f"No numeric values found in column {column!r}"}
    return {operation: _agg(values, operation), "count": len(values)}


def _agg(values: list[float], operation: str) -> float:
    if operation == "mean":
        return round(statistics.mean(values), 6)
    if operation == "sum":
        return round(sum(values), 6)
    if operation == "max":
        return max(values)
    if operation == "min":
        return min(values)
    if operation == "count":
        return float(len(values))
    return round(statistics.mean(values), 6)


def _linear_regression(values: list[float]) -> tuple[float, float]:
    """Return (slope, intercept) via ordinary least squares."""
    n = len(values)
    if n < 2:
        return 0.0, values[0] if values else 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    denom = sum((xs[i] - mean_x) ** 2 for i in range(n))
    slope = num / denom if denom != 0 else 0.0
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _forecast(values: list[float], horizon: int = 3) -> dict[str, Any]:
    slope, intercept = _linear_regression(values)
    n = len(values)
    forecasted = [round(intercept + slope * (n + h), 4) for h in range(horizon)]
    return {
        "historical_count": n,
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "forecast": forecasted,
        "trend": "up" if slope > 0.01 else ("down" if slope < -0.01 else "flat"),
    }


def _detect_anomalies_zscore(values: list[float], column: str = "value", threshold: float = 2.5) -> list[dict[str, Any]]:
    """Detect statistical anomalies in *values* using the z-score method.

    A value is flagged as anomalous when its z-score (distance from the mean in
    units of standard deviation) exceeds *threshold*.

    Parameters
    ----------
    values:
        Sequence of numeric values to analyse.
    column:
        Column name to include in each anomaly record for traceability.
    threshold:
        Z-score threshold above which a value is classified as an anomaly.
        Default is 2.5 (≈1% of a standard normal distribution).

    Returns
    -------
    list[dict]
        Each entry is ``{"index": int, "value": float, "z_score": float, "column": str}``.
        Returns an empty list when there are fewer than 3 values or the standard
        deviation is effectively zero.
    """
    if len(values) < 3:
        return []
    mean = statistics.mean(values)
    try:
        std = statistics.stdev(values)
    except statistics.StatisticsError:
        return []
    if std < 1e-9:
        return []
    anomalies = []
    for i, v in enumerate(values):
        z = abs(v - mean) / std
        if z > threshold:
            anomalies.append({"index": i, "value": round(v, 4), "z_score": round(z, 3), "column": column})
    return anomalies


def _run_analytics_query(data: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """Execute a natural-language analytics query over *data*."""
    if not data:
        return {"error": "Empty dataset", "query": query}

    columns = list(data[0].keys()) if data else []
    op = _parse_nl_query(query, columns)
    operation = op["operation"]

    if operation == "forecast":
        col = op.get("column") or (columns[-1] if columns else None)
        if col is None:
            return {"error": "No numeric column found for forecast"}
        values = []
        for row in data:
            try:
                v = float(row.get(col, 0.0))
                values.append(v)
            except (TypeError, ValueError):
                pass
        return {"query": query, "operation": "forecast", "column": col, **_forecast(values, horizon=int(op.get("horizon", 3)))}

    if operation == "anomaly_detection":
        col = op.get("column") or (columns[-1] if columns else None)
        if col is None:
            return {"error": "No column found for anomaly detection"}
        values = []
        for row in data:
            try:
                v = float(row.get(col, 0.0))
                values.append(v)
            except (TypeError, ValueError):
                pass
        anomalies = _detect_anomalies_zscore(values, column=col)
        return {
            "query": query,
            "operation": "anomaly_detection",
            "column": col,
            "total_records": len(values),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        }

    result = _apply_aggregation(data, operation, op.get("column"), op.get("group_by"), op.get("filter"))
    return {"query": query, "operation": operation, "column": op.get("column"), "group_by": op.get("group_by"), "result": result}


def _infer_schema(data: list[dict[str, Any]]) -> dict[str, str]:
    """Infer column types from the first few rows."""
    schema: dict[str, Any] = {}
    sample = data[:20]
    for row in sample:
        for k, v in row.items():
            if k in schema:
                continue
            if isinstance(v, bool):
                schema[k] = "bool"
            elif isinstance(v, int):
                schema[k] = "int"
            elif isinstance(v, float):
                schema[k] = "float"
            elif isinstance(v, str):
                schema[k] = "str"
            else:
                schema[k] = "unknown"
    return schema


def _validate_schema(data: list[dict[str, Any]], declared_schema: dict[str, str]) -> list[dict[str, Any]]:
    """Validate data rows against a declared type schema. Returns a list of violations."""
    type_map: dict[str, type] = {"int": (int,), "float": (int, float), "str": (str,), "bool": (bool,)}
    violations = []
    for i, row in enumerate(data):
        for col, expected_type in declared_schema.items():
            val = row.get(col)
            if val is None:
                continue
            expected = type_map.get(expected_type)
            if expected and not isinstance(val, expected):
                violations.append({"row": i, "column": col, "expected": expected_type, "got": type(val).__name__, "value": repr(val)})
    return violations


def _profile_data(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute column-level statistics for a dataset."""
    if not data:
        return {}
    schema = _infer_schema(data)
    profile: dict[str, Any] = {}
    total = len(data)
    for col, col_type in schema.items():
        null_count = sum(1 for r in data if r.get(col) is None)
        if col_type in ("int", "float"):
            values = []
            for r in data:
                try:
                    v = float(r.get(col, 0.0))
                    values.append(v)
                except (TypeError, ValueError):
                    pass
            if values:
                profile[col] = {
                    "type": col_type,
                    "count": len(values),
                    "null_count": null_count,
                    "mean": round(statistics.mean(values), 4),
                    "min": min(values),
                    "max": max(values),
                    "std": round(statistics.stdev(values) if len(values) > 1 else 0.0, 4),
                    "anomaly_count": len(_detect_anomalies_zscore(values, column=col)),
                }
            else:
                profile[col] = {"type": col_type, "null_count": null_count, "count": total - null_count}
        else:
            unique_vals: Counter = Counter(str(r.get(col, "")) for r in data if r.get(col) is not None)
            profile[col] = {
                "type": col_type,
                "count": total - null_count,
                "null_count": null_count,
                "unique_values": len(unique_vals),
                "top_values": dict(unique_vals.most_common(5)),
            }
    return {"total_rows": total, "columns": len(schema), "column_profiles": profile}


def _extract_knowledge_graph(text: str) -> dict[str, Any]:
    """Very lightweight knowledge-graph extraction from plain text.

    Uses pattern matching to find entity–relation–entity triples.
    Suitable for document understanding (contracts, reports) without
    requiring an LLM call.
    """
    # Entity recognition: capitalised multi-word tokens (naive NER)
    entity_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
    entities = list(set(entity_pattern.findall(text)))[:50]

    # Relation extraction: subject VERB object patterns
    relation_pattern = re.compile(
        r"\b([A-Z][a-zA-Z\s]+?)\s+(is|are|has|have|owns|provides|requires|supports|uses|depends on|integrates with|manages)\s+([A-Za-z][a-zA-Z\s]+?)(?:[,\.;]|$)",
        re.MULTILINE,
    )
    triples = []
    for m in relation_pattern.finditer(text):
        subject = m.group(1).strip()
        relation = m.group(2).strip()
        obj = m.group(3).strip()
        if subject and obj:
            triples.append({"subject": subject, "relation": relation, "object": obj})

    # Co-occurrence graph (entities that appear in same sentence)
    sentences = re.split(r"[.!?]\s+", text)
    cooccurrence: list[dict[str, Any]] = []
    for sent in sentences:
        ents_in_sent = [e for e in entities if e in sent]
        for i in range(len(ents_in_sent)):
            for j in range(i + 1, len(ents_in_sent)):
                cooccurrence.append({"entity1": ents_in_sent[i], "entity2": ents_in_sent[j], "sentence": sent[:100]})

    return {
        "entities": entities,
        "entity_count": len(entities),
        "triples": triples[:30],
        "triple_count": len(triples),
        "cooccurrence": cooccurrence[:20],
    }


def _run_data_pipeline(
    data: list[dict[str, Any]],
    declared_schema: dict[str, str],
    pipeline_steps: list[str],
) -> dict[str, Any]:
    """Execute a sequence of pipeline steps over *data*."""
    result: dict[str, Any] = {"steps_run": [], "row_count": len(data)}
    rows = list(data)

    for step in pipeline_steps:
        step = step.lower().strip()

        if step in ("validate_schema", "validate"):
            violations = _validate_schema(rows, declared_schema)
            result["schema_violations"] = violations
            result["schema_valid"] = len(violations) == 0
            result["steps_run"].append("validate_schema")

        elif step == "profile":
            result["profile"] = _profile_data(rows)
            result["steps_run"].append("profile")

        elif step in ("detect_anomalies", "anomaly_detection"):
            anomaly_report: dict[str, Any] = {}
            inferred = _infer_schema(rows)
            for col, col_type in inferred.items():
                if col_type in ("int", "float"):
                    values = []
                    for r in rows:
                        with contextlib.suppress(TypeError, ValueError):
                            values.append(float(r.get(col, 0.0)))
                    anomalies = _detect_anomalies_zscore(values, column=col)
                    if anomalies:
                        anomaly_report[col] = anomalies
            result["anomalies"] = anomaly_report
            result["steps_run"].append("detect_anomalies")

        elif step in ("deduplicate", "dedup"):
            seen = set()
            deduped = []
            for r in rows:
                key = repr(sorted(r.items()))
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            removed = len(rows) - len(deduped)
            rows = deduped
            result["deduplicated_rows"] = removed
            result["steps_run"].append("deduplicate")

        elif step in ("drop_nulls", "drop_null"):
            before = len(rows)
            rows = [r for r in rows if all(v is not None for v in r.values())]
            result["null_rows_dropped"] = before - len(rows)
            result["steps_run"].append("drop_nulls")

        elif step == "knowledge_graph":
            # Extract KG from string values in rows
            text_parts = []
            for r in rows[:50]:
                for v in r.values():
                    if isinstance(v, str) and len(v) > 20:
                        text_parts.append(v)
            combined_text = " ".join(text_parts[:20])
            result["knowledge_graph"] = _extract_knowledge_graph(combined_text)
            result["steps_run"].append("knowledge_graph")

    result["output_row_count"] = len(rows)
    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class AnalyticsBackend:
    """Zero-dependency analytics backend for Chimera Pilot.

    Handles ``ANALYTICS_QUERY`` and ``DATA_PIPELINE`` task kinds.
    """

    id = "analytics.local"
    name = "Ghost Chimera Analytics Engine"
    _description = "NL querying, anomaly detection, data pipeline validation, knowledge graph extraction"

    def __init__(self) -> None:
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.ANALYTICS_QUERY, TaskKind.DATA_PIPELINE},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            max_context_tokens=None,
            metadata={
                "pipeline_steps": ["validate_schema", "profile", "detect_anomalies", "deduplicate", "drop_nulls", "knowledge_graph"],
                "analytics_operations": ["count", "mean", "sum", "max", "min", "forecast", "anomaly_detection"],
            },
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=1.0, latency_ms=10)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        row_count = len(task.inputs.get("data") or [])
        latency = max(5, row_count // 100)  # ~100 rows/ms rough estimate
        return BackendHealth(available=True, reliability=1.0, latency_ms=latency, estimated_cost_usd=0.0)

    def execute(self, task: TaskSpec) -> ExecutionResult:
        try:
            if task.kind == TaskKind.ANALYTICS_QUERY:
                result = self._execute_analytics_query(task)
            elif task.kind == TaskKind.DATA_PIPELINE:
                result = self._execute_data_pipeline(task)
            else:
                raise ValueError(f"Unsupported task kind: {task.kind}")

            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=result.get("success", True),
                output=result,
                metrics={"kind": str(task.kind), "row_count": len(task.inputs.get("data") or [])},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analytics error: %s", exc)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output={},
                error=str(exc),
            )

    def _execute_analytics_query(self, task: TaskSpec) -> dict[str, Any]:
        query = str(task.inputs.get("query") or task.objective)
        data = list(task.inputs.get("data") or [])
        result = _run_analytics_query(data, query)
        result["success"] = "error" not in result
        return result

    def _execute_data_pipeline(self, task: TaskSpec) -> dict[str, Any]:
        data = list(task.inputs.get("data") or [])
        declared_schema = dict(task.inputs.get("schema") or {})
        pipeline = list(task.inputs.get("pipeline") or ["validate_schema", "profile", "detect_anomalies"])
        return _run_data_pipeline(data, declared_schema, pipeline)


__all__ = [
    "AnalyticsBackend",
    "_detect_anomalies_zscore",
    "_extract_knowledge_graph",
    "_forecast",
    "_profile_data",
    "_run_analytics_query",
    "_run_data_pipeline",
]
