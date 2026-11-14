import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sqlalchemy import select
from app.models import Device, Podcast, PodcastEpisode, PodcastProgress
from app.services.devices import initialize_pages
from app.services import podcasts as service


def device(db, name='child'):
    d=Device(device_id=name, name=name)
    initialize_pages(d)
    next(p for p in d.pages if p.page_id=='podcasts').enabled=True
    db.add(d); db.commit()
    return d

def channel(db, d=None, count=0):
    p=Podcast(name='Wissen',url='https://example.org/podcast.xml')
    db.add(p);db.flush()
    for i in range(count):
        db.add(PodcastEpisode(id=f'{i:064x}',podcast_id=p.id,external_id=str(i),title=f'Folge {i}',
            published_at=datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(days=i),duration=120,
            url=f'https://example.org/{i}.mp3',mime_type='audio/mpeg',supported=True))
    if d: d.podcast_ids=[p.id]
    db.commit();return p

def rss(items):
    return ('<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Test</title>'+items+'</channel></rss>').encode()

def entry(guid='stable',url='https://example.org/1.mp3',mime='audio/mpeg',duration='1:02:03'):
    return f'<item><guid>{guid}</guid><title>Eine &amp; Folge</title><description>&lt;b&gt;Hallo&lt;/b&gt;</description><pubDate>Mon, 12 Jan 2026 12:00:00 GMT</pubDate><itunes:duration>{duration}</itunes:duration><enclosure url="{url}" type="{mime}"/></item>'

def test_rss_stable_guids_duplicates_changed_url_removed_and_unsupported(db):
    p=channel(db)
    service.parse(rss(entry()+entry()+entry('aac','https://example.org/other.aac','audio/aac','wrong')),p,db)
    db.commit();rows=db.scalars(select(PodcastEpisode).order_by(PodcastEpisode.supported.desc())).all()
    assert len(rows)==2
    first=rows[0];stable_id=first.id
    assert first.duration==3723 and first.description=='Hallo' and first.title=='Eine & Folge'
    assert rows[1].duration is None and not rows[1].supported
    service.parse(rss(entry(url='https://example.org/new.mp3')),p,db);db.commit()
    assert first.id==stable_id and first.url.endswith('new.mp3')
    assert not rows[1].available
    service.parse(rss(entry('aac','https://example.org/other.aac','audio/aac')),p,db);db.commit()
    assert not first.available
    service.parse(rss(entry()),p,db);db.commit()
    assert first.available
    with pytest.raises(ValueError): service.parse(b'<html>oops</html>',p,db)

@pytest.mark.parametrize('value,expected',[('20',20),('03:04',184),('1:02:03',3723),('1.5',1),('-1',None),('nan',None),('inf',None),('bad',None),('999999999',None),('',None)])
def test_duration(value,expected): assert service.duration(value)==expected


def test_atom_enclosure_and_relative_url(db):
    p=channel(db)
    service.parse(b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><id>urn:episode:1</id><title>Test</title><updated>2026-01-01T00:00:00Z</updated><link rel="enclosure" href="/one.MP3" type="application/octet-stream"/></entry></feed>''',p,db)
    e=db.scalar(select(PodcastEpisode));assert e.supported and e.url=='https://example.org/one.MP3'


def test_all_episodes_pagination_grants_and_resume(client,db):
    d=device(db);other=device(db,'other');p=channel(db,d,57)
    base=f'/api/v1/devices/{d.device_id}/podcasts'
    assert client.get(f'/api/v1/devices/{other.device_id}/podcasts/{p.id}/episodes').status_code==404
    assert client.get(base+f'/{p.id}/episodes?limit=100').status_code==422
    seen=[];offset=0
    while True:
        data=client.get(base+f'/{p.id}/episodes?offset={offset}').json()
        assert data['total']==57
        seen.extend(e['id'] for e in data['episodes'])
        if data['nextOffset'] is None:break
        offset=data['nextOffset']
    assert len(set(seen))==57 and seen[0]==f'{0:064x}' and seen[-1]==f'{56:064x}'
    assert client.get(base+'/resume').json()=={'episode':None}
    body={'podcastId':p.id,'episodeId':seen[30],'position':40,'duration':120,'status':'partial','revision':1700000000000}
    assert client.post(base+'/progress',json=body).json()['ok']
    resumed=client.get(base+'/resume').json()
    assert resumed['episode']['id']==seen[30] and resumed['offset']==30 and resumed['episode']['position']==40
    # Revision makes offline retries idempotent; a delayed packet cannot overwrite newer progress.
    assert client.post(base+'/progress',json={**body,'position':5,'revision':2}).json()['revision']==body['revision']
    assert client.get(base+'/resume').json()['episode']['position']==40
    assert client.get(f'/api/v1/devices/{other.device_id}/podcasts/resume').json()['episode'] is None
    d.podcast_ids=[];db.commit()
    assert client.get(base+'/resume').json()['episode'] is None
    assert client.post(base+'/progress',json=body).status_code==404
    d.podcast_ids=[p.id];next(x for x in d.pages if x.page_id=='podcasts').enabled=False;db.commit()
    assert client.get(base+f'/{p.id}/episodes').status_code==404
    assert client.get(f'/api/v1/devices/{d.device_id}/config').json()['podcasts']==[]


def test_completion_next_unheard_channel_scope_and_replay(client,db):
    d=device(db);p=channel(db,d,3);base='/api/v1/devices/child/podcasts'
    body={'podcastId':p.id,'episodeId':f'{0:064x}','position':120,'duration':120,'status':'completed','revision':10}
    assert client.post(base+'/progress',json=body).status_code==422
    assert client.post(base+'/progress',json={**body,'naturalEnd':True}).status_code==200
    assert client.get(base+f'/{p.id}/next?after={0:064x}').json()['episode']['id']==f'{1:064x}'
    for i in [1,2]:
        assert client.post(base+'/progress',json={**body,'episodeId':f'{i:064x}','naturalEnd':True,'revision':10+i}).status_code==200
    assert client.get(base+f'/{p.id}/next').json()['episode'] is None
    # Fully heard episodes remain selectable and a manual replay starts a new partial state.
    assert client.get(base+f'/{p.id}/episodes').json()['episodes'][0]['status']=='completed'
    assert client.post(base+'/progress',json={**body,'status':'partial','position':0,'revision':20}).status_code==200
    assert client.get(base+f'/{p.id}/next').json()['episode']['id']==f'{0:064x}'
    e=db.get(PodcastEpisode,f'{0:064x}');e.available=False;db.commit()
    assert client.get(base+f'/{p.id}/episodes/{e.id}').status_code==404
    assert client.get(base+f'/{p.id}/next').json()['episode'] is None

@pytest.mark.asyncio
async def test_fetch_redirects_policy_errors_and_catalog_retention(db,monkeypatch):
    p=channel(db,count=1);checked=[]
    monkeypatch.setattr(service,'validate_external_url',lambda url:checked.append(url))
    responses=[httpx.Response(302,headers={'Location':'/rss'}),httpx.Response(200,content=rss(entry()))]
    transport=httpx.MockTransport(lambda request: responses.pop(0))
    original=httpx.AsyncClient
    monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    assert await service.fetch(p,db)
    assert checked==['https://example.org/podcast.xml','https://example.org/rss']
    previous=p.last_success
    responses.append(httpx.Response(200,content=b'broken'))
    assert not await service.fetch(p,db)
    assert p.last_error and p.last_success==previous
    assert len(db.scalars(select(PodcastEpisode).where(PodcastEpisode.available.is_(True))).all())==1


def test_admin_crud_sort_grants_and_duplicate_device(client,db,monkeypatch):
    async def noop(*args):return True
    monkeypatch.setattr(service,'fetch',noop)
    d=device(db)
    for name,pos in [('Second',2),('First',1)]:
        assert client.post('/podcasts',data={'name':name,'url':f'https://example.org/{name}.xml','enabled':'true','position':pos},follow_redirects=False).status_code==303
    rows=service.channels(db)
    assert [p.name for p in rows]==['First','Second']
    response=client.post(f'/devices/{d.id}',data={'name':d.name,'age':8,'avatar':'dragon','enabled':'true','page_ids':['home','podcasts'],'podcast_settings':'true','podcast_ids':[p.id for p in rows]},follow_redirects=False)
    assert response.status_code==303
    assert len(client.get('/api/v1/devices/child/config').json()['podcasts'])==2
    before=d.config_version
    assert client.post(f'/podcasts/{rows[0].id}',data={'name':'First','url':rows[0].url,'position':1},follow_redirects=False).status_code==303
    assert d.config_version==before+1
    assert len(client.get('/api/v1/devices/child/config').json()['podcasts'])==1
    assert client.post(f'/devices/{d.id}/duplicate',follow_redirects=False).status_code==303
    copied=db.scalar(select(Device).where(Device.device_id=='child-copy'));assert copied.podcast_ids==d.podcast_ids
    assert client.get('/podcasts').status_code==200
    assert client.get(f'/podcasts/{rows[0].id}/episodes').status_code==200
    assert client.post('/podcasts',data={'name':'Bad','url':'ftp://example.org/x'}).status_code==422
    assert client.post('/podcasts',data={'name':'Duplicate','url':rows[0].url}).status_code==409
    assert client.post(f'/podcasts/{rows[1].id}/delete',follow_redirects=False).status_code==303
    db.expire_all();assert rows[1].id not in d.podcast_ids


def test_migration_preserves_radio_and_existing_config(tmp_path):
    path=tmp_path/'migration.db'
    env={**os.environ,'LEAP_DATABASE_URL':f'sqlite:///{path}','LEAP_DATA_DIR':str(tmp_path)}
    def run(*args):subprocess.run([sys.executable,*args],env=env,check=True,capture_output=True)
    run('-m','alembic','upgrade','0024')
    run('-c',"""from app.core.database import SessionLocal
from app.models import Device,DevicePage,RadioStation
with SessionLocal() as db:
 db.add(RadioStation(name='Keep',url='https://example.org/radio'))
 d=Device(device_id='old',name='Old',config_version=7,radio_station_ids=[1])
 d.pages=[DevicePage(page_id='radio',title='Radio',enabled=True,position=5,settings={'keep':True})]
 db.add(d);db.commit()
""")
    with sqlite3.connect(path) as c:
        c.execute('ALTER TABLE devices DROP COLUMN podcast_ids');c.execute('ALTER TABLE devices DROP COLUMN podcast_last')
        for name in ['podcast_progress','podcast_episodes','podcasts']:c.execute(f'DROP TABLE {name}')
    run('-m','alembic','upgrade','head');run('-m','alembic','upgrade','head')
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT config_version,radio_station_ids,podcast_ids,podcast_last FROM devices').fetchone()==(8,'[1]','[]','{}')
        assert c.execute("SELECT enabled,position FROM device_pages WHERE page_id='podcasts'").fetchone()==(0,6)
        assert c.execute("SELECT enabled,position FROM device_pages WHERE page_id='radio'").fetchone()==(1,5)
    run('-m','alembic','downgrade','0024')
    with sqlite3.connect(path) as c:assert c.execute('SELECT radio_station_ids FROM devices').fetchone()==('[1]',)


def test_deleted_device_cannot_leave_progress_for_reused_id(client, db):
    d=device(db);p=channel(db,d,1)
    body={'podcastId':p.id,'episodeId':f'{0:064x}','position':20,'status':'partial','revision':1}
    assert client.post('/api/v1/devices/child/podcasts/progress',json=body).status_code==200
    assert db.scalar(select(PodcastProgress)) is not None
    assert client.post(f'/devices/{d.id}/delete',follow_redirects=False).status_code==303
    assert db.scalar(select(PodcastProgress)) is None
