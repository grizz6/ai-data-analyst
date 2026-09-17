import asyncio
import time

import httpx

from app.main import app
from app.services import pipeline

SLOW_SECONDS = 0.6


def test_health_stays_responsive_while_a_file_is_being_analyzed(monkeypatch, sample_csv_bytes):
    real_compute = pipeline.compute_analysis

    def slow_compute(file_bytes, filename):
        time.sleep(SLOW_SECONDS)  # blocking, like a big pandas job
        return real_compute(file_bytes, filename)

    monkeypatch.setattr(pipeline, "compute_analysis", slow_compute)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = time.perf_counter()
            upload = asyncio.create_task(
                client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")})
            )
            await asyncio.sleep(0.1)  # let the upload reach the pipeline

            health = await client.get("/api/health")
            health_done = time.perf_counter() - started
            upload_result = await upload
            upload_done = time.perf_counter() - started

            return health, health_done, upload_result, upload_done

    health, health_done, upload, upload_done = asyncio.run(scenario())

    assert health.status_code == 200
    assert upload.status_code == 200
    # Timed from the start of the upload: if the pipeline blocked the event loop,
    # health could not even be sent until the slow job had finished.
    assert health_done < SLOW_SECONDS
    assert health_done < upload_done
