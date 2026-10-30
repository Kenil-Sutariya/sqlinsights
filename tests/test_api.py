from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_seeded_demo(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "mode": "demo"}
    datasets = client.get("/api/v1/datasets").json()
    assert datasets == [
        {
            "id": "retail_demo",
            "name": "Retail Demo",
            "table_count": 3,
            "created_at": datasets[0]["created_at"],
            "protected": True,
        }
    ]
    schema = client.get("/api/v1/datasets/retail_demo/schema").json()
    assert [table["name"] for table in schema["tables"]] == ["customers", "products", "orders"]
    assert [table["row_count"] for table in schema["tables"]] == [6, 6, 18]


def test_dataset_upload_preview_and_delete(client: TestClient) -> None:
    created = client.post("/api/v1/datasets", json={"name": "My data"})
    assert created.status_code == 201
    dataset_id = created.json()["id"]
    content = b"Order ID,Net Amount\n0007,12.50\n0008,\n"
    uploaded = client.post(
        f"/api/v1/datasets/{dataset_id}/tables",
        files={"file": ("Sales 2026.csv", content, "text/csv")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json() == {
        "name": "sales_2026",
        "source_filename": "Sales 2026.csv",
        "row_count": 2,
        "columns": [
            {"name": "order_id", "source_name": "Order ID", "type": "TEXT"},
            {"name": "net_amount", "source_name": "Net Amount", "type": "REAL"},
        ],
    }
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/preview", params={"table": "sales_2026", "limit": 10}
    )
    assert preview.json()["rows"] == [["0007", 12.5], ["0008", None]]
    assert client.delete(f"/api/v1/datasets/{dataset_id}").status_code == 200
    assert client.get(f"/api/v1/datasets/{dataset_id}/schema").status_code == 404


def test_demo_cannot_be_deleted(client: TestClient) -> None:
    response = client.delete("/api/v1/datasets/retail_demo")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_PROTECTED"
