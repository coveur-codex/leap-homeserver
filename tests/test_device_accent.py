from app.models import Device
from app.services.devices import initialize_pages

def test_accent_config_form_validation_and_duplicate(client, db):
    d=Device(device_id='accent', name='Accent')
    initialize_pages(d); db.add(d); db.commit()
    url=f'/devices/{d.id}'
    config='/api/v1/devices/accent/config'
    assert client.get(config).json()['accentColor']=='#00d7c5'
    assert 'name="accent_color"' in client.get(url).text
    form={'name':'Accent','age':8,'avatar':'dragon','accent_color':'#FF9933','enabled':'on'}
    assert client.post(url,data=form,follow_redirects=False).status_code==303
    assert client.get(config).json()['accentColor']=='#ff9933'
    version=d.config_version
    assert client.post(url,data={**form,'accent_color':'#bad<script>'},follow_redirects=False).status_code==422
    assert d.config_version==version
    client.post(f'{url}/duplicate',follow_redirects=False)
    assert client.get('/api/v1/devices/accent-copy/config').json()['accentColor']=='#ff9933'
