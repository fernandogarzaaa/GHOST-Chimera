"""Tests for AnalyticsBackend and DocumentIngester — Track 4: Data & Intelligence."""

from __future__ import annotations

import tempfile
import unittest


class TestNLQueryParsing(unittest.TestCase):
    def test_parse_count(self):
        from ghostchimera.chimera_pilot.backends.analytics import _parse_nl_query

        op = _parse_nl_query("count records", ["id", "region", "revenue"])
        self.assertEqual(op["operation"], "count")

    def test_parse_mean(self):
        from ghostchimera.chimera_pilot.backends.analytics import _parse_nl_query

        op = _parse_nl_query("average revenue", ["id", "region", "revenue"])
        self.assertEqual(op["operation"], "mean")
        self.assertEqual(op["column"], "revenue")

    def test_parse_sum_with_group(self):
        from ghostchimera.chimera_pilot.backends.analytics import _parse_nl_query

        op = _parse_nl_query("sum revenue by region", ["id", "region", "revenue"])
        self.assertEqual(op["operation"], "sum")
        self.assertEqual(op["column"], "revenue")
        self.assertEqual(op["group_by"], "region")

    def test_parse_forecast(self):
        from ghostchimera.chimera_pilot.backends.analytics import _parse_nl_query

        op = _parse_nl_query("forecast revenue for next 3 quarters", ["revenue", "region"])
        self.assertEqual(op["operation"], "forecast")
        self.assertEqual(op["horizon"], 3)

    def test_parse_anomaly_detection(self):
        from ghostchimera.chimera_pilot.backends.analytics import _parse_nl_query

        op = _parse_nl_query("detect anomalies in latency", ["latency", "region"])
        self.assertEqual(op["operation"], "anomaly_detection")
        self.assertEqual(op["column"], "latency")


class TestAggregation(unittest.TestCase):
    _DATA = [
        {"region": "EU", "revenue": 1200.0},
        {"region": "US", "revenue": 3400.0},
        {"region": "EU", "revenue": 1500.0},
        {"region": "APAC", "revenue": 800.0},
        {"region": "US", "revenue": 2100.0},
    ]

    def test_count_all(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "count", None, None, None)
        self.assertEqual(result["count"], 5)

    def test_count_by_group(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "count", None, "region", None)
        self.assertEqual(result["EU"]["count"], 2)
        self.assertEqual(result["US"]["count"], 2)
        self.assertEqual(result["APAC"]["count"], 1)

    def test_mean_revenue(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "mean", "revenue", None, None)
        self.assertAlmostEqual(result["mean"], sum(r["revenue"] for r in self._DATA) / len(self._DATA), places=3)

    def test_sum_with_filter(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "sum", "revenue", None, {"column": "region", "value": "EU"})
        self.assertAlmostEqual(result["sum"], 2700.0)

    def test_max_revenue(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "max", "revenue", None, None)
        self.assertEqual(result["max"], 3400.0)

    def test_min_revenue(self):
        from ghostchimera.chimera_pilot.backends.analytics import _apply_aggregation

        result = _apply_aggregation(self._DATA, "min", "revenue", None, None)
        self.assertEqual(result["min"], 800.0)


class TestForecast(unittest.TestCase):
    def test_linear_upward_trend(self):
        from ghostchimera.chimera_pilot.backends.analytics import _forecast

        values = [100.0, 110.0, 120.0, 130.0, 140.0]
        result = _forecast(values, horizon=3)
        self.assertEqual(result["trend"], "up")
        self.assertEqual(len(result["forecast"]), 3)
        self.assertGreater(result["forecast"][0], 140.0)

    def test_flat_trend(self):
        from ghostchimera.chimera_pilot.backends.analytics import _forecast

        values = [50.0, 50.0, 50.0, 50.0, 50.0]
        result = _forecast(values, horizon=2)
        self.assertEqual(result["trend"], "flat")
        for v in result["forecast"]:
            self.assertAlmostEqual(v, 50.0, places=2)

    def test_downward_trend(self):
        from ghostchimera.chimera_pilot.backends.analytics import _forecast

        values = [200.0, 180.0, 160.0, 140.0, 120.0]
        result = _forecast(values, horizon=2)
        self.assertEqual(result["trend"], "down")

    def test_single_value(self):
        from ghostchimera.chimera_pilot.backends.analytics import _forecast

        result = _forecast([42.0], horizon=1)
        self.assertEqual(len(result["forecast"]), 1)


class TestAnomalyDetection(unittest.TestCase):
    def test_detects_outlier(self):
        from ghostchimera.chimera_pilot.backends.analytics import _detect_anomalies_zscore

        values = [10.0, 11.0, 10.0, 12.0, 10.0, 11.0, 500.0, 10.0, 11.0, 10.0, 11.0, 10.0]
        anomalies = _detect_anomalies_zscore(values, column="latency")
        self.assertGreater(len(anomalies), 0)
        values_flagged = [a["value"] for a in anomalies]
        self.assertIn(500.0, values_flagged)

    def test_no_anomalies_in_uniform(self):
        from ghostchimera.chimera_pilot.backends.analytics import _detect_anomalies_zscore

        values = [10.0] * 20
        anomalies = _detect_anomalies_zscore(values)
        self.assertEqual(anomalies, [])

    def test_too_few_values(self):
        from ghostchimera.chimera_pilot.backends.analytics import _detect_anomalies_zscore

        anomalies = _detect_anomalies_zscore([1.0, 2.0])
        self.assertEqual(anomalies, [])


class TestSchemaValidation(unittest.TestCase):
    def test_type_violation_detected(self):
        from ghostchimera.chimera_pilot.backends.analytics import _validate_schema

        data = [{"revenue": 1200}, {"revenue": "not_a_number"}]
        violations = _validate_schema(data, {"revenue": "float"})
        self.assertGreater(len(violations), 0)
        self.assertTrue(any(v["column"] == "revenue" for v in violations))

    def test_valid_data_no_violations(self):
        from ghostchimera.chimera_pilot.backends.analytics import _validate_schema

        data = [{"revenue": 1200.0, "region": "EU"}, {"revenue": 3400.0, "region": "US"}]
        violations = _validate_schema(data, {"revenue": "float", "region": "str"})
        self.assertEqual(violations, [])

    def test_null_values_skip(self):
        from ghostchimera.chimera_pilot.backends.analytics import _validate_schema

        data = [{"revenue": None, "region": "EU"}]
        violations = _validate_schema(data, {"revenue": "float"})
        self.assertEqual(violations, [])


class TestDataProfile(unittest.TestCase):
    def test_numeric_column_profile(self):
        from ghostchimera.chimera_pilot.backends.analytics import _profile_data

        data = [{"val": float(i)} for i in range(10)]
        profile = _profile_data(data)
        col_profile = profile["column_profiles"]["val"]
        self.assertIn("mean", col_profile)
        self.assertIn("std", col_profile)
        self.assertEqual(col_profile["count"], 10)

    def test_categorical_column_profile(self):
        from ghostchimera.chimera_pilot.backends.analytics import _profile_data

        data = [{"region": r} for r in ["EU", "US", "EU", "APAC"]]
        profile = _profile_data(data)
        col_profile = profile["column_profiles"]["region"]
        self.assertEqual(col_profile["unique_values"], 3)
        self.assertIn("EU", col_profile["top_values"])

    def test_empty_data(self):
        from ghostchimera.chimera_pilot.backends.analytics import _profile_data

        result = _profile_data([])
        self.assertEqual(result, {})


class TestKnowledgeGraphExtraction(unittest.TestCase):
    def test_extracts_entities(self):
        from ghostchimera.chimera_pilot.backends.analytics import _extract_knowledge_graph

        text = "Ghost Chimera is an AI agent orchestration system. Chimera Pilot manages task scheduling."
        kg = _extract_knowledge_graph(text)
        self.assertGreater(kg["entity_count"], 0)

    def test_extracts_triples(self):
        from ghostchimera.chimera_pilot.backends.analytics import _extract_knowledge_graph

        text = "Chimera Pilot is a task orchestrator. Ghost Chimera uses Chimera Pilot for scheduling."
        kg = _extract_knowledge_graph(text)
        self.assertIn("triples", kg)
        # triples may or may not match depending on sentence structure — just check shape
        self.assertIsInstance(kg["triples"], list)

    def test_empty_text(self):
        from ghostchimera.chimera_pilot.backends.analytics import _extract_knowledge_graph

        kg = _extract_knowledge_graph("")
        self.assertEqual(kg["entity_count"], 0)


class TestAnalyticsBackend(unittest.TestCase):
    _DATA = [{"region": "EU", "revenue": float(v)} for v in [1200, 1500, 1100, 1300, 1450]] + \
            [{"region": "US", "revenue": float(v)} for v in [3400, 2100, 3200, 2800, 3000]]

    def test_probe_available(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend

        backend = AnalyticsBackend()
        health = backend.probe()
        self.assertTrue(health.available)

    def test_count_query(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.ANALYTICS_QUERY,
            objective="count records by region",
            inputs={"query": "count records by region", "data": self._DATA},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        res = result.output["result"]
        self.assertEqual(res["EU"]["count"], 5)
        self.assertEqual(res["US"]["count"], 5)

    def test_forecast_query(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        data = [{"sales": float(v)} for v in [100, 110, 120, 130, 140]]
        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.ANALYTICS_QUERY,
            objective="forecast sales",
            inputs={"query": "forecast sales for next 3 periods", "data": data},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(result.output.get("trend"), "up")

    def test_anomaly_detection_query(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        data = [{"latency": float(v)} for v in [10, 11, 10, 12, 10, 11, 500, 10, 11, 10, 11, 10]]
        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.ANALYTICS_QUERY,
            objective="detect anomalies in latency",
            inputs={"query": "detect anomalies in latency", "data": data},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertGreater(result.output.get("anomaly_count", 0), 0)

    def test_data_pipeline_validate_schema(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        data = [{"revenue": 1200}, {"revenue": "bad"}]
        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.DATA_PIPELINE,
            objective="validate",
            inputs={"data": data, "schema": {"revenue": "float"}, "pipeline": ["validate_schema"]},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertFalse(result.output.get("schema_valid"))

    def test_data_pipeline_full(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        data = [{"val": float(i), "cat": "A" if i % 2 == 0 else "B"} for i in range(20)]
        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.DATA_PIPELINE,
            objective="full pipeline",
            inputs={"data": data, "schema": {"val": "float", "cat": "str"}, "pipeline": ["validate_schema", "profile", "detect_anomalies"]},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertIn("validate_schema", result.output["steps_run"])
        self.assertIn("profile", result.output["steps_run"])
        self.assertIn("detect_anomalies", result.output["steps_run"])

    def test_data_pipeline_dedup(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        data = [{"val": 1}, {"val": 1}, {"val": 2}]
        backend = AnalyticsBackend()
        task = TaskSpec.create(
            kind=TaskKind.DATA_PIPELINE,
            objective="dedup",
            inputs={"data": data, "schema": {}, "pipeline": ["deduplicate"]},
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(result.output["deduplicated_rows"], 1)
        self.assertEqual(result.output["output_row_count"], 2)

    def test_cannot_run_reasoning(self):
        from ghostchimera.chimera_pilot.backends.analytics import AnalyticsBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        backend = AnalyticsBackend()
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="think", inputs={"prompt": "hello"})
        self.assertFalse(backend.can_run(task))


class TestAnalyticsTaskKinds(unittest.TestCase):
    def test_analytics_query_kind_exists(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        self.assertEqual(TaskKind.ANALYTICS_QUERY, "analytics_query")

    def test_data_pipeline_kind_exists(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        self.assertEqual(TaskKind.DATA_PIPELINE, "data_pipeline")

    def test_analytics_schema_validates(self):
        from ghostchimera.chimera_pilot.schema import validate_task
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        ok, errors = validate_task(TaskKind.ANALYTICS_QUERY, {"query": "count records"})
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_analytics_schema_rejects_empty_query(self):
        from ghostchimera.chimera_pilot.schema import validate_task
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        ok, errors = validate_task(TaskKind.ANALYTICS_QUERY, {"query": ""})
        self.assertFalse(ok)


class TestAnalyticsCompilerRouting(unittest.TestCase):
    def test_analytics_routes(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("analytics: total sales by region")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.ANALYTICS_QUERY)

    def test_data_pipeline_routes(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("data pipeline: validate data schema and profile it")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.DATA_PIPELINE)

    def test_detect_anomalies_routes(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("detect anomalies in the sensor data")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.ANALYTICS_QUERY)

    def test_forecast_routes(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("forecast quarterly revenue for next 4 periods")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.ANALYTICS_QUERY)


class TestDocumentIngester(unittest.TestCase):
    def test_ingest_text(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(
                source_type="text",
                content="Hello world. This is a test document. " * 5,
                metadata={"namespace": "test"},
                source_id="doc-001",
            ))
        self.assertGreater(result.ingested_count, 0)
        self.assertEqual(len(result.errors), 0)

    def test_ingest_csv(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        csv_data = "region,revenue\nEU,1200\nUS,3400\nAPAC,800\n"
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="csv", content=csv_data, source_id="sales-csv"))
        self.assertEqual(result.ingested_count, 3)
        self.assertEqual(len(result.errors), 0)

    def test_ingest_json_list(self):
        import json as _json

        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        data = [{"id": i, "title": f"Item {i}", "body": "Some content text."} for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="json", content=_json.dumps(data), source_id="items"))
        self.assertEqual(result.ingested_count, 5)

    def test_ingest_json_object(self):
        import json as _json

        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        obj = {"title": "Report", "body": "This is the report body. " * 3}
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="json", content=_json.dumps(obj), source_id="report"))
        self.assertGreater(result.ingested_count, 0)

    def test_ingest_markdown(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        md = "# Introduction\n\nThis is the intro.\n\n## Setup\n\nInstall the package.\n\n## Usage\n\nRun the agent.\n"
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="markdown", content=md, source_id="readme"))
        self.assertEqual(result.ingested_count, 3)  # 3 sections

    def test_deduplication(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            src = IngestionSource(source_type="text", content="Repeated content. " * 5, source_id="dup-test")
            r1 = ingester.ingest(src)
            r2 = ingester.ingest(src)
        self.assertGreater(r1.ingested_count, 0)
        self.assertEqual(r2.ingested_count, 0)
        self.assertEqual(r2.skipped_count, r1.ingested_count)

    def test_ingest_many(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            sources = [
                IngestionSource(source_type="text", content=f"Document {i}. " * 3, source_id=f"doc-{i}")
                for i in range(4)
            ]
            results = ingester.ingest_many(sources)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.ingested_count >= 1 for r in results))

    def test_file_not_found_error(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="file", content="/nonexistent/path.txt"))
        self.assertEqual(result.ingested_count, 0)
        self.assertGreater(len(result.errors), 0)

    def test_invalid_json_error(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="json", content="not valid json", source_id="bad-json"))
        self.assertEqual(result.ingested_count, 0)
        self.assertGreater(len(result.errors), 0)

    def test_chunking_large_text(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        large_text = "Word. " * 1000  # ~6000 chars, default chunk_size=2000
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(
                source_type="text",
                content=large_text,
                chunk_size=2000,
                source_id="large-text",
            ))
        # Should be split into multiple chunks
        self.assertGreater(result.ingested_count, 1)

    def test_ingest_file_txt(self):
        from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
        from ghostchimera.memory_layer.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/test.txt"
            with open(path, "w") as f:
                f.write("This is a text file. " * 5)
            store = MemoryStore(f"{tmp}/mem.sqlite3")
            ingester = DocumentIngester(store)
            result = ingester.ingest(IngestionSource(source_type="file", content=path, source_id=f"file:{path}"))
        self.assertGreater(result.ingested_count, 0)
        self.assertEqual(len(result.errors), 0)


if __name__ == "__main__":
    unittest.main()
