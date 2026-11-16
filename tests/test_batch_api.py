from fastapi.testclient import TestClient

from parkfolio.api import create_app
from parkfolio.batch import Batch
from parkfolio.model import Conflict, DomainError, MissingReference
from tests.common import Case, event


class BatchTests(Case):
    def test_batch_cursor_resumes_without_double_count(self):
        batch = Batch(self.service)
        events = [event("door", "batch-open", "visit_open", "10:00:00",
                        {"visit_id": "V1", "visitor_id": "A", "store_id": "S1", "space_id": "R1"}),
                  event("shelf", "batch-read", "reading", "10:10:00",
                        {"visit_id": "V1", "book_id": "B1", "minutes": 15})]
        paused = batch.load("batch-1", events, stop_after=1)
        self.assertEqual(paused["cursor"], 1)
        self.assertFalse(paused["completed"])
        resumed = batch.load("batch-1", events)
        self.assertEqual(resumed["cursor"], 2)
        self.assertTrue(resumed["completed"])
        self.assertEqual(self.service.overview()["readings"], 1)

    def test_batch_replay_does_not_duplicate_outcomes(self):
        batch = Batch(self.service)
        events = [event("door", "open-b", "visit_open", "10:00:00",
                        {"visit_id": "V1", "visitor_id": "A", "store_id": "S1", "space_id": "R1"})]
        batch.load("b", events)
        repeated = batch.load("b", events)
        self.assertEqual(len(repeated["outcomes"]), 1)
        self.assertEqual(self.service.overview()["visits"], 1)

    def test_batch_manifest_change_conflicts(self):
        batch = Batch(self.service)
        batch.load("b", [])
        with self.assertRaises(Conflict):
            batch.load("b", [{"not": "same"}])

    def test_batch_invalid_item_is_recorded_rejected(self):
        batch = Batch(self.service)
        result = batch.load("b", [{"not": "an event"}])
        self.assertEqual(result["outcomes"][0]["status"], "rejected")
        self.assertTrue(result["completed"])

    def test_batch_quarantined_input_can_retry_after_reference(self):
        batch = Batch(self.service)
        events = [event("shelf", "r", "reading", "10:10:00",
                        {"visit_id": "V1", "book_id": "B1", "minutes": 9})]
        result = batch.load("b", events)
        self.assertEqual(result["outcomes"][0]["status"], "quarantined")
        self.open()
        self.assertEqual(self.service.events.retry(result["outcomes"][0]["event_id"])["status"], "applied")

    def test_batch_rejects_negative_stop_after(self):
        with self.assertRaises(DomainError):
            Batch(self.service).load("b", [], stop_after=-1)

    def test_batch_unknown_status(self):
        with self.assertRaises(MissingReference):
            Batch(self.service).status("missing")

    def test_batch_empty_manifest_completes(self):
        result = Batch(self.service).load("empty", [])
        self.assertTrue(result["completed"])
        self.assertEqual(result["cursor"], 0)


class ApiTests(Case):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app(self.service.store.path))

    def test_health_reports_overview(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overview"]["books"], 2)

    def test_api_ingest_and_mart(self):
        payload = event("door", "api-open", "visit_open", "10:00:00",
                        {"visit_id": "V1", "visitor_id": "A", "store_id": "S1", "space_id": "R1"})
        response = self.client.post("/events", json=payload)
        self.assertEqual(response.status_code, 200)
        report = self.client.get("/mart/2026-07")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["stores"][0]["visits"], 1)

    def test_api_conflicting_event_is_409(self):
        self.open()
        payload = event("door", "open-V1", "visit_open", "10:01:00",
                        {"visit_id": "V1", "visitor_id": "A", "store_id": "S1", "space_id": "R1"})
        response = self.client.post("/events", json=payload)
        self.assertEqual(response.status_code, 409)

    def test_api_unknown_reference_is_404(self):
        response = self.client.post("/spaces", json={"space_id": "X", "store_id": "none",
            "kind": "reading", "capacity": 1, "valid_from": "2026-07-01T00:00:00Z"})
        self.assertEqual(response.status_code, 404)

    def test_api_invalid_input_is_422(self):
        response = self.client.post("/spaces", json={"space_id": "X", "store_id": "S1",
            "kind": "reading", "capacity": 0, "valid_from": "2026-07-01T00:00:00Z"})
        self.assertEqual(response.status_code, 422)

    def test_api_batch_and_status(self):
        response = self.client.post("/batches", json={"batch_id": "api-batch", "events": []})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/batches/api-batch").json()["completed"])

    def test_api_quality_and_lineage(self):
        opened = self.open()
        quality = self.client.get("/quality/2026-07")
        self.assertTrue(quality.json()["ready"])
        lineage = self.client.get(f"/events/{opened['event_id']}").json()
        self.assertEqual(lineage["projections"]["visit_open"][0]["visit_id"], "V1")

    def test_api_export_and_analysis(self):
        self.open()
        self.read()
        csv = self.client.get("/export/2026-07/csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("reading_minutes", csv.text)
        funnel = self.client.get("/analysis/2026-07/S1/funnel")
        self.assertEqual(funnel.json()["readers"], 1)

    def test_api_release_round_trip(self):
        self.open()
        preview = self.client.get("/releases/preview/2026-07").json()
        response = self.client.post("/releases", json={"name": "july", "month": "2026-07",
            "expected_fingerprint": preview["fingerprint"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/releases/july").json()["snapshot"]["stores"][0]["visits"], 1)
