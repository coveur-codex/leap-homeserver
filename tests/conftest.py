import os
os.environ["LEAP_DATABASE_URL"]="sqlite://"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base,get_db
from app.main import app
@pytest.fixture
def db(tmp_path, monkeypatch):
 from app.core.config import settings
 monkeypatch.setattr(settings,"data_dir",tmp_path)
 engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(engine);s=sessionmaker(bind=engine,expire_on_commit=False)();yield s;s.close()
@pytest.fixture
def client(db, monkeypatch):
 monkeypatch.setattr("app.main.SessionLocal",sessionmaker(bind=db.bind,expire_on_commit=False))
 app.dependency_overrides[get_db]=lambda:db
 with TestClient(app) as c:yield c
 app.dependency_overrides.clear()
