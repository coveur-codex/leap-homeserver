from datetime import datetime,timezone
from io import BytesIO
from types import SimpleNamespace
import asyncio
import pytest
from PIL import Image
from app.models import Article,Category,Device,Feed,QuizCatalog,QuizQuestion
from app.services.devices import initialize_pages
from app.services.feeds import clean_text,parse_feed
from app.services import feeds as feed_service
from app.services.images import resize_image

def make_device(db,age=9):
 d=Device(device_id="leap-erik",name="Erik",age=age);initialize_pages(d);db.add(d);db.commit();return d
def test_device_creation_and_config(client,db):
 r=client.post("/devices",data={"device_id":"leap-erik","name":"Erik","age":42,"avatar":"redpanda","avatar_name":"Rudi"},follow_redirects=False);assert r.status_code==303
 config=client.get("/api/v1/devices/leap-erik/config").json()
 assert config["pages"][0]["id"]=="home"
 assert (config["age"],config["avatar"],config["avatarName"])==(42,"redpanda","Rudi")
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
 assert '/static/avatars/dragon.svg' in page.text
 assert client.get('/static/avatars/dragon.svg').status_code==200

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
