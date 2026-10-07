from datetime import datetime,timezone
from io import BytesIO
from types import SimpleNamespace
import asyncio
import pytest
from PIL import Image
from bs4 import BeautifulSoup
from app.models import Article,Category,Device,Feed,LocationCache,QuizCatalog,QuizQuestion
from app.services.devices import initialize_pages
from app.services.feeds import clean_text,parse_feed
from app.services import feeds as feed_service
from app.services import location_data
from app.services.images import resize_image

def make_device(db,age=9):
 d=Device(device_id="leap-erik",name="Erik",age=age);initialize_pages(d);db.add(d);db.commit();return d
def test_device_creation_and_config(client,db):
 r=client.post("/devices",data={"device_id":"leap-erik","name":"Erik","age":42,"avatar":"redpanda","avatar_name":"Rudi"},follow_redirects=False);assert r.status_code==303
 config=client.get("/api/v1/devices/leap-erik/config").json()
 assert config["pages"][0]["id"]=="home"
 assert (config["age"],config["avatar"],config["avatarName"])==(42,"redpanda","Rudi")
 assert {g["id"] for g in config["games"] if g["enabled"]} == {"tamagotchi","snake","hot_potato","simon_motion","tilt_maze","connect_four","kitchen","crab_journey"}
 page=client.get("/devices").text
 assert 'max="18"' not in page and "frog" in page and "redpanda" in page
def test_config_version(client,db):
 d=make_device(db);before=d.config_version
 client.post(f"/devices/{d.id}",data={"name":"E","age":64,"avatar":"frog","avatar_name":"Freddy","enabled":"on","page_ids":["home"]});db.refresh(d)
 assert d.config_version==before+1
 assert (d.age,d.avatar,d.avatar_name)==(64,"frog","Freddy")

def test_device_id_can_be_changed_but_must_stay_unique(client,db):
 d=make_device(db)
 page=client.get(f"/devices/{d.id}")
 assert 'name="device_id"' in page.text and 'value="leap-erik"' in page.text
 other=Device(device_id="leap-anna",name="Anna");initialize_pages(other);db.add(other);db.commit()
 form={"device_id":"leap-papa","name":"Papa","age":42,"avatar":"dragon"}
 response=client.post(f"/devices/{d.id}",data=form,follow_redirects=False)
 db.refresh(d)
 assert response.status_code==303 and d.device_id=="leap-papa"
 form["device_id"]="leap-anna"
 assert client.post(f"/devices/{d.id}",data=form).status_code==409
 form["device_id"]="LEAP Papa"
 assert client.post(f"/devices/{d.id}",data=form).status_code==422
 form["device_id"]="a"*81
 assert client.post(f"/devices/{d.id}",data=form).status_code==422
def test_clean_html(): assert clean_text("<p>Hallo&nbsp;  Welt</p>")=="Hallo Welt"
def test_feed_parse_and_dedupe(db):
 c=Category(slug="technik",name="Technik");db.add(c);db.flush();f=Feed(name="Test",url="https://example.com/rss",category=c,image_mode="disabled");db.add(f);db.commit()
 xml=b'''<rss version="2.0"><channel><title>T</title><item><guid>1</guid><title>A &amp; B</title><link>https://example.com/a</link><description><![CDATA[<p>Text</p>]]></description><pubDate>Sun, 28 Sep 2025 10:00:00 GMT</pubDate></item></channel></rss>'''
 assert parse_feed(xml,f,db)[0]==1;assert parse_feed(xml,f,db)[0]==0;assert db.query(Article).one().summary=="Text"

@pytest.mark.asyncio
async def test_feed_images_are_downloaded_concurrently(monkeypatch):
 active=peak=0
 async def download(url,article_id,mode,client):
  nonlocal active,peak
  active+=1;peak=max(peak,active)
  await asyncio.sleep(.01)
  active-=1
  return f"original-{article_id}",f"leap-{article_id}"
 monkeypatch.setattr(feed_service,"download_and_process_async",download)
 articles=[SimpleNamespace(id=i,image_original=None,image_leap=None) for i in range(8)]
 count=await feed_service._download_images([(article,f"https://example.com/{article.id}.jpg") for article in articles],"fit",object())
 assert count==8 and peak==feed_service.IMAGE_DOWNLOAD_CONCURRENCY
 assert articles[-1].image_leap=="leap-7"
def test_image_scaling():
 b=BytesIO();Image.new("RGB",(400,100),"red").save(b,"PNG");assert resize_image(b.getvalue(),(120,80),"center_crop").size==(120,80)
def test_interest_news_api(client,db):
 d=make_device(db);c=Category(slug="technik",name="Technik");d.categories.append(c);f=Feed(name="F",url="https://x.test",category=c);db.add_all([c,f]);db.flush();db.add(Article(feed=f,category="technik",title="T",summary="S",source="F",url="https://x/a",published_at=datetime.now(timezone.utc),hash="x"));db.commit();assert len(client.get("/api/v1/devices/leap-erik/news").json()["articles"])==1
def test_quiz_age_filter(client,db):
 d=make_device(db,8);cat=QuizCatalog(name="C");cat.questions=[QuizQuestion(question="jung",answers=["a","b","c","d"],min_age=7),QuizQuestion(question="alt",answers=["a","b","c","d"],min_age=10)];d.quiz_catalogs.append(cat);db.commit();assert [q["q"] for q in client.get("/api/v1/devices/leap-erik/quiz").json()["questions"]]==["jung"]

def test_device_preview_layout_and_avatar(client,db):
 d=make_device(db)
 page=client.get(f"/devices/{d.id}")
 assert page.status_code==200
 assert 'class="leap-sidebar"' in page.text
 assert 'class="leap-card news-card"' in page.text
 assert '/api/v1/packages/avatar-dragon/versions/1/files/preview.png' in page.text
 assert 'data-preview-card="HOME"' in page.text
 assert client.get('/static/avatars/dragon.svg').status_code==200

def test_device_preview_follows_enabled_page_configuration(client,db):
 d=make_device(db)
 for page in d.pages:
  page.enabled=page.page_id in {"home","quiz"}
  page.position=1 if page.page_id=="quiz" else 2
 cat=QuizCatalog(name="Wissen")
 cat.questions=[QuizQuestion(question="Wie viele Kontinente gibt es?",answers=["Fünf","Sechs","Sieben","Acht"],min_age=7)]
 d.quiz_catalogs.append(cat);db.commit()
 preview=client.get(f"/devices/{d.id}").text
 assert preview.index('data-preview-card="QUIZ"') < preview.index('data-preview-card="HOME"')
 assert 'data-preview-card="WETTER"' not in preview
 assert 'data-preview-card="NEWS"' not in preview
 assert "Katalog auswählen" in preview and "Wissen" in preview and "Mathe-Quiz" in preview
 assert "Wie viele Kontinente gibt es?" not in preview
 assert all(answer not in preview for answer in ("Fünf","Sechs","Sieben","Acht"))

def test_device_preview_carousel_uses_device_news_selection(client,db):
 d=make_device(db)
 selected=Category(slug="selected",name="Selected")
 hidden=Category(slug="hidden",name="Hidden")
 d.categories.append(selected)
 selected_feed=Feed(name="Selected Feed",url="https://selected.test",category=selected)
 hidden_feed=Feed(name="Hidden Feed",url="https://hidden.test",category=hidden)
 db.add_all([selected,hidden,selected_feed,hidden_feed]);db.flush()
 now=datetime.now(timezone.utc)
 db.add_all([
  Article(feed=selected_feed,category="selected",title="First selected",summary="One",source="Selected Feed",url="https://selected.test/1",published_at=now,hash="selected-1"),
  Article(feed=selected_feed,category="selected",title="Second selected",summary="Two",source="Selected Feed",url="https://selected.test/2",published_at=now,hash="selected-2"),
  Article(feed=hidden_feed,category="hidden",title="Must stay hidden",summary="No",source="Hidden Feed",url="https://hidden.test/1",published_at=now,hash="hidden-1"),
 ]);db.commit()
 page=client.get(f"/devices/{d.id}")
 assert page.text.count("data-news-slide") == 2
 assert "First selected" in page.text and "Second selected" in page.text
 assert "Must stay hidden" not in page.text
 assert "data-news-next" in page.text and "1 / 2" in page.text
 assert client.get('/static/device-preview.js').status_code==200

@pytest.mark.asyncio
async def test_location_refresh_fetches_shared_coordinates_once(db):
 calls={"weather":0,"aircraft":0}
 class Weather:
  async def current(self,latitude,longitude,unit):
   calls["weather"]+=1
   return {"updated":"now","unit":"C","current":{"temperature":18,"weatherCode":1,"windSpeed":7},"today":{"min":9,"max":20,"precipitationProbability":5}}
 class Aircraft:
  async def nearby(self,latitude,longitude,radius):
   calls["aircraft"]+=1
   return {"updated":"now","radiusNm":radius,"aircraft":[{"hex":"abc123","callsign":"LEAP1","registration":"D-TEST","type":"A320","latitude":52.5,"longitude":13.4,"altitudeFeet":12000,"groundSpeedKnots":250,"trackDegrees":90,"distanceNm":3.2}]}
 first=Device(device_id="leap-one",name="One",weather_location="Berlin",latitude=52.52,longitude=13.405)
 second=Device(device_id="leap-two",name="Two",weather_location="Berlin",latitude=52.52,longitude=13.405)
 initialize_pages(first);initialize_pages(second);db.add_all([first,second]);db.commit()
 count=await location_data.refresh_configured_locations(db,weather_provider=Weather(),aircraft_provider=Aircraft())
 assert count==1 and calls=={"weather":1,"aircraft":1}
 assert first.weather_version==2 and second.weather_version==2
 assert first.aircraft_version==2 and second.aircraft_version==2
 cache=location_data.cache_for_device(first,db)
 assert cache.weather_data["location"]=="Berlin"
 assert cache.aircraft_data["aircraft"][0]["callsign"]=="LEAP1"

def test_weather_aircraft_api_and_preview_use_shared_cache(client,db,monkeypatch):
 class Weather:
  async def current(self,latitude,longitude,unit):
   return {"updated":"now","unit":"C","current":{"temperature":18,"weatherCode":1,"windSpeed":7},"today":{"min":9,"max":20,"precipitationProbability":5}}
 class Aircraft:
  async def nearby(self,latitude,longitude,radius):
   return {"updated":"now","radiusNm":radius,"aircraft":[{"hex":"abc123","callsign":"LEAP1","registration":"D-TEST","type":"A320","latitude":52.5,"longitude":13.4,"altitudeFeet":12000,"groundSpeedKnots":250,"trackDegrees":90,"distanceNm":3.2}]}
 monkeypatch.setattr(location_data,"OpenMeteoProvider",Weather)
 monkeypatch.setattr(location_data,"AdsbLolProvider",Aircraft)
 device=make_device(db);device.weather_location="Berlin";device.latitude=52.52;device.longitude=13.405;db.commit()
 next(page for page in device.pages if page.page_id=="aircraft").enabled=True;db.commit()
 weather=client.get("/api/v1/devices/leap-erik/weather")
 aircraft=client.get("/api/v1/devices/leap-erik/aircraft")
 assert weather.status_code==200 and weather.json()["current"]["temperature"]==18
 assert aircraft.status_code==200 and aircraft.json()["aircraft"][0]["callsign"]=="LEAP1"
 assert aircraft.json()["center"] == {"latitude":52.52,"longitude":13.405}
 assert "aircraftVersion" in client.get("/api/v1/devices/leap-erik/sync").json()
 preview=client.get(f"/devices/{device.id}").text
 assert 'data-preview-card="WETTER"' in preview and "Berlin" in preview
 assert 'data-latitude="52.52"' in preview and 'data-longitude="13.405"' in preview
 assert 'data-preview-card="FLUGRADAR"' in preview and "LEAP1" in preview


def test_system_page_shows_runtime_and_refresh_times(client,db):
 fetched=datetime(2026,9,30,12,0,tzinfo=timezone.utc)
 db.add(LocationCache(location_key="52.52000,13.40500",location="Berlin",latitude=52.52,longitude=13.405,weather_fetched_at=fetched,weather_data={},aircraft_fetched_at=fetched,aircraft_data={}))
 db.add(Feed(name="Feed",url="https://example.test/feed",last_success=fetched))
 db.commit()
 page=client.get("/system")
 assert page.status_code==200
 assert "Letzter Start" in page.text and "Laufzeit" in page.text
 assert "Wetter und Flugradar" in page.text and "Berlin" in page.text
 assert page.text.count("30.09.2026, 12:00:00") == 3
 assert "Nächste Prüfung ab" in page.text and "12:15:00" in page.text


def enable_knowledge(device, db, source="klexikon"):
 page=next(page for page in device.pages if page.page_id=="knowledge")
 page.enabled=True;device.knowledge_source=source;db.commit()


def test_knowledge_configuration_and_preview(client,db):
 device=make_device(db)
 settings=BeautifulSoup(client.get(f"/devices/{device.id}").text,"html.parser")
 pages=settings.find("h2",string="Seiten").parent
 assert pages.select_one('input[name="page_ids"][value="knowledge"]') is not None
 assert len(pages.select('input[name="page_positions"][type="number"]'))==len(device.pages)
 assert settings.find("h2",string="Standort") is not None
 assert settings.select_one('input[name="knowledge_enabled"]') is None
 form={"device_id":device.device_id,"name":device.name,"age":device.age,"avatar":device.avatar,"enabled":"on","page_ids":["home","knowledge"],"knowledge_source":"miniklexikon"}
 form["page_positions"]=[2 if page.page_id=="home" else 1 if page.page_id=="knowledge" else page.position for page in device.pages]
 response=client.post(f"/devices/{device.id}",data=form,follow_redirects=False)
 db.refresh(device)
 assert response.status_code==303 and device.knowledge_source=="miniklexikon"
 assert next(page for page in device.pages if page.page_id=="knowledge").enabled
 config=client.get(f"/api/v1/devices/{device.device_id}/config").json()
 assert config["knowledgeSource"]=="miniklexikon"
 preview=client.get(f"/devices/{device.id}").text
 assert 'data-preview-card="WISSEN"' in preview
 assert "MiniKlexikon" in preview and "knowledge-saturn.svg" in preview
 assert preview.index('data-preview-card="WISSEN"') < preview.index('data-preview-card="HOME"')
 settings=BeautifulSoup(preview,"html.parser")
 assert settings.select_one('select[name="knowledge_source"] option[selected]')["value"]=="miniklexikon"
 assert settings.select_one('input[name="page_ids"][value="knowledge"]').has_attr("checked")
 form["page_ids"]=["home"]
 response=client.post(f"/devices/{device.id}",data=form,follow_redirects=False)
 assert response.status_code==303
 config=client.get(f"/api/v1/devices/{device.device_id}/config").json()
 assert config["knowledgeSource"]=="miniklexikon"
 assert not next(page for page in config["pages"] if page["id"]=="knowledge")["enabled"]
 assert 'data-preview-card="WISSEN"' not in client.get(f"/devices/{device.id}").text
 assert client.get(f"/api/leap/{device.device_id}/knowledge/article/Saturn").status_code==403


def test_knowledge_api_uses_device_source_and_checks_activation(client,db,monkeypatch):
 device=make_device(db)
 assert client.get(f"/api/leap/{device.device_id}/knowledge/article/Saturn").status_code==403
 enable_knowledge(device,db,"miniklexikon")
 calls=[]
 async def article(source,title):
  calls.append(("article",source,title));return {"title":title,"source":source,"text":"Text","image":None,"links":[]}
 async def search(source,query,limit):
  calls.append(("search",source,query));return {"source":source,"results":[]}
 async def random(source):
  calls.append(("random",source));return {"title":"Zufall","source":source,"text":"Text","image":None,"links":[]}
 monkeypatch.setattr("app.api.routes.knowledge_service.article",article)
 monkeypatch.setattr("app.api.routes.knowledge_service.search",search)
 monkeypatch.setattr("app.api.routes.knowledge_service.random_article",random)
 assert client.get(f"/api/leap/{device.device_id}/knowledge/article/Saturn").json()["source"]=="miniklexikon"
 assert client.get(f"/api/leap/{device.device_id}/knowledge/search?q=wal").json()["results"]==[]
 assert client.get(f"/api/leap/{device.device_id}/knowledge/random").json()["title"]=="Zufall"
 assert calls==[("article","miniklexikon","Saturn"),("search","miniklexikon","wal"),("random","miniklexikon")]
 assert client.get("/api/leap/unbekannt/knowledge/random").status_code==404


@pytest.mark.asyncio
async def test_knowledge_article_is_cleaned_linked_and_cached(monkeypatch,tmp_path):
 from app.services import knowledge
 monkeypatch.setattr(knowledge.settings,"data_dir",tmp_path)
 calls=0
 async def request(source,params,client):
  nonlocal calls
  calls+=1
  return {"query":{"pages":[{"title":"Saturn","extract":"<p>Der <b>Saturn</b> ist ein Planet.</p><p>Er hat Ringe.</p>","thumbnail":{"source":"https://images.example/saturn.jpg"},"links":[{"title":"Planet"},{"title":"Jupiter"}]}]}}
 async def image(source,url,client): return "a"*32
 monkeypatch.setattr(knowledge,"_request",request)
 monkeypatch.setattr(knowledge,"_cache_image",image)
 first=await knowledge.article("klexikon","Saturn")
 second=await knowledge.article("klexikon","Saturn")
 assert calls==1 and first==second
 assert first["text"]=="Der Saturn ist ein Planet.\n\nEr hat Ringe."
 assert first["image"].endswith("/"+"a"*32+".jpg")
 assert first["links"]==[{"title":"Planet","ref":"Planet"},{"title":"Jupiter","ref":"Jupiter"}]
 assert first["originalUrl"].endswith("/wiki/Saturn") and first["license"]


def test_knowledge_search_rejects_invalid_query(client,db):
 device=make_device(db);enable_knowledge(device,db)
 response=client.get(f"/api/leap/{device.device_id}/knowledge/search?q=x")
 assert response.status_code==422
 assert "zwischen 2 und 80" in response.json()["detail"]
