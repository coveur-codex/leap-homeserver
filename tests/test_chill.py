import hashlib
import json
from io import BytesIO
from pathlib import Path
import zipfile
from PIL import Image
from sqlalchemy import select
from app.models import AssetPackage, AssetVersion
from app.services import distribution as service
from tests.test_distribution import device, sync, event

BUNDLES = Path(__file__).resolve().parents[1] / 'app/defaults/chill'


def test_shipped_packages_and_idempotent_adoption(client, db):
    service.ensure_packages(db)
    for path in BUNDLES.glob('*.zip'):
        key = path.name.removesuffix('-v1.zip')
        package = db.get(AssetPackage, key)
        assert package.kind == 'chill' and package.current_version == 1
        manifest = service.current(db, package).manifest
        service.validate_chill(manifest['definition'], service.file_map(service.current(db, package)))
        with zipfile.ZipFile(path) as archive:
            for item in manifest['files']:
                content = client.get(item['url']).content
                assert hashlib.sha256(content).hexdigest() == item['sha256']
                if item['path'].endswith('.png'):
                    assert content == archive.read(item['path'])
                    image = Image.open(BytesIO(content)); image.load()
                    assert image.mode == 'RGBA' and image.info.get('interlace', 0) == 0
    count = len(db.scalars(select(AssetVersion)).all())
    service.ensure_packages(db)
    assert len(db.scalars(select(AssetVersion)).all()) == count


def test_scene_selection_preview_sync_and_delayed_cleanup(client, db):
    d = device(db)
    def choose(scene):
        return client.post(f'/devices/{d.id}', data={'name': 'Test', 'age': 8, 'avatar': 'dragon', 'enabled': 'true', 'distribution_settings': 'true', 'chill_id': scene}, follow_redirects=False)
    assert choose('chill-space').status_code == 303
    first = sync(client, firmware='1.0.0-beta.18')
    assert 'chill-space' in first['desiredAssets'] and 'chill-fire' not in first['desiredAssets']
    assert any(u['packageId'] == 'chill-space' for u in first['assetUpdates'])
    preview = client.get(f'/devices/{d.id}').text
    assert 'data-preview-card="RUHEZEIT"' in preview and 'data-scene="space"' in preview
    assert choose('chill-snow').status_code == 303
    second = sync(client, first['desiredAssets'], firmware='1.0.0-beta.18')
    assert 'chill-snow' in second['desiredAssets'] and 'chill-space' not in second['desiredAssets']
    assert not second['cleanupAllowed']
    result = event(client, second, event='boot_success', firmwareVersion='1.0.0-beta.18', installedAssets=second['desiredAssets']).json()
    assert {'packageId': 'chill-space', 'version': 1} in result['removeVersions']
    assert choose('missing').status_code == 422
    response = client.post(f'/devices/{d.id}', data={'name': 'Test', 'age': 8, 'avatar': 'dragon', 'distribution_settings': 'true', 'content_ids': ['chill-snow', 'chill-fire']})
    assert response.status_code == 422
    assert choose('').status_code == 303
    assert not any(k.startswith('chill-') for k in sync(client)['desiredAssets'])


def test_original_zip_manifest_import_and_references(client, db):
    # Reconstruct the original manifest syntax (pattern + frame count, no scene field).
    with zipfile.ZipFile(BUNDLES/'chill-fire-v1.zip') as src:
        source = json.loads(src.read('manifest.json'))
        source.pop('scene'); source['id'] = 'chill_fire_v1'
        flame = source['sprites'][2]; flame.pop('frames'); flame['pattern'] = 'sprites/flame_%02d_72x96.png'; flame['frames'] = 6
        raw = BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for name in src.namelist():
                archive.writestr(name, json.dumps(source) if name == 'manifest.json' else src.read(name))
    response = client.post('/assets/chill-fire/files', data={'expected': 1}, files={'files': ('chill_fire_v1.zip', raw.getvalue())}, follow_redirects=False)
    assert response.status_code == 303, response.text
    manifest = service.current(db, db.get(AssetPackage, 'chill-fire')).manifest
    assert manifest['definition']['scene'] == 'fire'
    assert len(manifest['definition']['sprites'][2]['frames']) == 6
    assert 'manifest.json' not in {f['path'] for f in manifest['files']}
    assert client.post('/assets/chill-fire/files/delete', data={'expected': 2, 'path': 'sprites/flame_00_72x96.png'}).status_code == 422
    assert db.get(AssetPackage, 'chill-fire').current_version == 2


def test_legacy_selection_is_single_and_old_firmware_is_blocked(client, db):
    d = device(db); d.content_selection = ['chill-snow', 'chill-fire']; db.commit()
    plan = sync(client, firmware='1.0.0-beta.17')
    assert [k for k in plan['desiredAssets'] if k.startswith('chill-')] == ['chill-fire']
    assert not any(u['packageId'].startswith('chill-') for u in plan['assetUpdates'])


def test_malformed_zip_metadata_and_unsupported_scene_are_rejected(client, db):
    with zipfile.ZipFile(BUNDLES/'chill-snow-v1.zip') as src:
        source = json.loads(src.read('manifest.json'))
    for mutation in ({'slider': []}, {'scene': []}, {'sprites': [{'pattern': '%d.png', 'frames': 999}]}):
        raw = BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({**source, **mutation}))
        response = client.post('/assets/chill-snow/files', data={'expected': 1}, files={'files': ('bad.zip', raw.getvalue())})
        assert response.status_code == 422, response.text
        assert db.get(AssetPackage, 'chill-snow').current_version == 1
