import pytest

TEST_TOKEN = "test-token-0123456789abcdef0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 懒加载:避免无 DB 依赖的测试因导入 platformdirs 失败
    from fastapi.testclient import TestClient

    from control_plane.api.app import create_app
    from control_plane.infrastructure.config import Settings

    from .fakes import make_fake_adapters

    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", TEST_TOKEN)
    settings = Settings(data_dir=str(tmp_path))
    app = create_app(settings, adapters=make_fake_adapters())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
        yield c


def wait_for_operation(client, operation_id: str, timeout: float = 10.0) -> dict:
    # 轮询 Operation 直到终态
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/operations/{operation_id}")
        assert r.status_code == 200
        op = r.json()
        if op["status"] in ("succeeded", "failed", "canceled"):
            return op
        time.sleep(0.05)
    raise AssertionError(f"operation {operation_id} 未在 {timeout}s 内完成")
