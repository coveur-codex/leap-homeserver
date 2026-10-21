import pytest
from app.models import Device
from app.services.devices import initialize_pages
from app.services.device_settings import target_numbers, server_url

@pytest.mark.parametrize('text,expected', [('9,10',[9,10]),('3-5,4,10',[3,4,5,10]),(' 1 , 100 ',[1,100])])
def test_targets(text, expected):
    assert target_numbers(text)==expected

@pytest.mark.parametrize('text', ['', '0','101','10-3','3,,4','1-1000000','1.5','-1','3-'])
def test_bad_targets(text):
    with pytest.raises(ValueError): target_numbers(text)

@pytest.mark.parametrize('value', ['ftp://server','http://user:pass@server','http://server/path','http://server?x=1','http://server:99999','http://bad host'])
def test_bad_server(value):
    with pytest.raises(ValueError): server_url(value)

def test_network_device_isolation_and_password_not_rendered(client, db):
    a=Device(device_id='one',name='One'); b=Device(device_id='two',name='Two')
    initialize_pages(a);initialize_pages(b);db.add_all([a,b]);db.commit()
    response=client.post(f'/devices/{a.id}/network/wifi',data={'ssid':'Travel','password':'secret123'},follow_redirects=False)
    assert response.status_code==303
    network=client.get('/api/v1/devices/one/network-config')
    assert network.headers['cache-control']=='no-store'
    assert network.json()['wifiProfiles']==[{'ssid':'Travel','password':'secret123'}]
    assert client.get('/api/v1/devices/two/network-config').json()['wifiProfiles']==[]
    assert 'secret123' not in client.get(f'/devices/{a.id}').text
    assert 'secret123' not in client.get('/api/v1/devices/one/config').text
    revision=network.json()['revision']
    assert client.post(f'/devices/{a.id}/network/wifi',data={'ssid':'Travel','password':'short'}).status_code==422
    assert client.get('/api/v1/devices/one/network-config').json()['revision']==revision
    client.post(f'/devices/{a.id}/network',data={'server':'http://ndk.tstromi.de:8080'},follow_redirects=False)
    assert client.get('/api/v1/devices/one/network-config').json()['revision']==revision+1
    for ssid in ['Two','Three','Four']:
        assert client.post(f'/devices/{a.id}/network/wifi',data={'ssid':ssid},follow_redirects=False).status_code==303
    assert client.post(f'/devices/{a.id}/network/wifi',data={'ssid':'Five'}).status_code==422
    client.post(f'/devices/{a.id}/network/remove',data={'ssid':'Travel'},follow_redirects=False)
    assert all(p['ssid']!='Travel' for p in client.get('/api/v1/devices/one/network-config').json()['wifiProfiles'])
    assert client.post(f'/devices/{a.id}/math-lab',data={'targets':'9,10,12-15'},follow_redirects=False).status_code==303
    assert client.get('/api/v1/devices/one/config').json()['mathLab']=={'targets':[9,10,12,13,14,15]}
    assert client.get('/api/v1/devices/two/config').json()['mathLab']=={'targets':[10]}
    copy=client.post(f'/devices/{a.id}/duplicate',follow_redirects=False)
    assert copy.status_code==303
    assert client.get('/api/v1/devices/one-copy/config').json()['mathLab']=={'targets':[9,10,12,13,14,15]}
