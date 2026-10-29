"""Queue size must not increase the rows loaded to start the next job."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.orm import Session

from jav_data.config import Settings
from jav_data.database import Base, make_engine
from jav_data.downloads import DownloadWorker
from jav_data.jobs import ScrapeWorker
from jav_data.models import MediaAsset, Movie, ScrapeJob


@pytest.fixture
def queued_database(tmp_path):
    settings = Settings(tmp_path / "data", tmp_path / "library")
    settings.prepare()
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(
            insert(Movie),
            [{"id": 1, "distribution_product_id": "example001", "title": "Synthetic"}],
        )
        session.execute(
            insert(ScrapeJob),
            [
                {"url": f"https://video.dmm.co.jp/av/content/?id=example{i:05d}"}
                for i in range(1105)
            ],
        )
        session.execute(
            insert(MediaAsset),
            [
                {
                    "movie_id": 1,
                    "kind": "cover",
                    "filename": f"cover{i:05d}.jpg",
                    "url": "https://pics.dmm.co.jp/cover.jpg",
                }
                for i in range(1105)
            ],
        )
        session.commit()
    try:
        yield settings, engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["scrape", "cover"])
def test_next_job_only_materializes_the_oldest_queued_record(queued_database, monkeypatch, kind):
    settings, engine = queued_database
    model = ScrapeJob if kind == "scrape" else MediaAsset
    loaded = []

    def record_load(record, _context):
        loaded.append(record.id)

    def stop_before_network(*_args, **_kwargs):
        raise ValueError("Synthetic test failure")

    if kind == "scrape":
        worker = ScrapeWorker(settings, engine)
        worker.browser = SimpleNamespace(new_page=stop_before_network)
    else:
        worker = DownloadWorker(settings, engine)
        monkeypatch.setattr("jav_data.downloads.build_opener", stop_before_network)

    event.listen(model, "load", record_load)
    try:
        worker.process_next()
    finally:
        event.remove(model, "load", record_load)

    # Includes the later failure update, but no other queued record is materialized.
    assert loaded and set(loaded) == {1}
    with Session(engine) as session:
        statuses = session.execute(select(model.id, model.status).order_by(model.id)).all()
    assert statuses[0] == (1, "failed")
    assert all(status == "queued" for _identifier, status in statuses[1:])
