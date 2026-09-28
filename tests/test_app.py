from datetime import datetime,timezone
from io import BytesIO
from PIL import Image
from app.models import Article,Category,Device,Feed,QuizCatalog,QuizQuestion
from app.services.devices import initialize_pages
from app.services.feeds import clean_text,parse_feed
from app.services.images import resize_image

def make_device(db,age=9):
 d=Device(device_id="leap-erik",name="Erik",age=age);initialize_pages(d);db.add(d);db.commit();return d
def test_device_creation_and_config(client,db):
 r=client.post("/devices",data={"device_id":"leap-erik","name":"Erik","age":9,"avatar":"dragon"},follow_redirects=False);assert r.status_code==303
 assert client.get("/api/v1/devices/leap-erik/config").json()["pages"][0]["id"]=="home"
def test_config_version(client,db):
 d=make_device(db);before=d.config_version
 client.post(f"/devices/{d.id}",data={"name":"E","age":9,"avatar":"dragon","enabled":"on","page_ids":["home"]});db.refresh(d);assert d.config_version==before+1
def test_clean_html(): assert clean_text("<p>Hallo&nbsp;  Welt</p>")=="Hallo Welt"
def test_feed_parse_and_dedupe(db):
 c=Category(slug="technik",name="Technik");db.add(c);db.flush();f=Feed(name="Test",url="https://example.com/rss",category=c,image_mode="disabled");db.add(f);db.commit()
 xml=b'''<rss version="2.0"><channel><title>T</title><item><guid>1</guid><title>A &amp; B</title><link>https://example.com/a</link><description><![CDATA[<p>Text</p>]]></description><pubDate>Sun, 28 Sep 2025 10:00:00 GMT</pubDate></item></channel></rss>'''
 assert parse_feed(xml,f,db)[0]==1;assert parse_feed(xml,f,db)[0]==0;assert db.query(Article).one().summary=="Text"
def test_image_scaling():
 b=BytesIO();Image.new("RGB",(400,100),"red").save(b,"PNG");assert resize_image(b.getvalue(),(120,80),"center_crop").size==(120,80)
def test_interest_news_api(client,db):
 d=make_device(db);c=Category(slug="technik",name="Technik");d.categories.append(c);f=Feed(name="F",url="https://x.test",category=c);db.add_all([c,f]);db.flush();db.add(Article(feed=f,category="technik",title="T",summary="S",source="F",url="https://x/a",published_at=datetime.now(timezone.utc),hash="x"));db.commit();assert len(client.get("/api/v1/devices/leap-erik/news").json()["articles"])==1
def test_quiz_age_filter(client,db):
 d=make_device(db,8);cat=QuizCatalog(name="C");cat.questions=[QuizQuestion(question="jung",answers=["a","b","c","d"],min_age=7),QuizQuestion(question="alt",answers=["a","b","c","d"],min_age=10)];d.quiz_catalogs.append(cat);db.commit();assert [q["q"] for q in client.get("/api/v1/devices/leap-erik/quiz").json()["questions"]]==["jung"]
