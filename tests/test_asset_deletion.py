from sqlalchemy import select, text

from app.models import AssetPackage, AssetVersion, QuizCatalog, QuizQuestion
from app.services import distribution as service
from tests.test_distribution import create, device, event, sync


def delete(client, package_id, expected=1, confirmed='true'):
    return client.post(f'/assets/{package_id}/delete',
        data={'expected': expected, 'confirmed': confirmed}, follow_redirects=False)


def test_confirmation_page_does_not_delete_and_requires_explicit_confirmation(client, db):
    create(client, 'chill-duplicate')
    d = device(db)
    d.content_selection = ['chill-duplicate']
    db.commit()
    assert '/assets/chill-duplicate/delete' in client.get('/assets/chill-duplicate').text
    response = client.get('/assets/chill-duplicate/delete')
    assert response.status_code == 200
    assert 'chill-duplicate' in response.text and d.device_id in response.text
    assert 'Abbrechen' in response.text and 'name="confirmed"' in response.text
    assert 'required' in response.text
    assert db.get(AssetPackage, 'chill-duplicate') is not None
    for data in [{'expected': 1}, {'expected': 1, 'confirmed': 'false'}]:
        assert client.post('/assets/chill-duplicate/delete', data=data).status_code == 422
        assert db.get(AssetPackage, 'chill-duplicate') is not None
    assert d.content_selection == ['chill-duplicate']


def test_delete_removes_all_versions_preserves_shared_blobs_and_sync_cleanup(client, db):
    create(client, 'chill-duplicate')
    create(client, 'chill-keep')
    for package_id in ['chill-duplicate', 'chill-keep']:
        assert client.post(f'/assets/{package_id}/files', data={'expected': 1},
            files={'files': ('fish.png', b'shared')}, follow_redirects=False).status_code == 303
    kept = client.get('/api/v1/packages/chill-keep/versions/2/manifest').json()
    d = device(db)
    d.content_selection = ['chill-duplicate', 'chill-keep']
    d.installed_assets = {'chill-duplicate': 2}
    db.commit()
    version = d.config_version
    old_plan = sync(client, d.installed_assets)
    response = delete(client, 'chill-duplicate', expected=2)
    assert response.status_code == 303
    assert response.headers['location'] == '/assets?kind=chill'
    assert db.get(AssetPackage, 'chill-duplicate') is None
    assert not db.scalars(select(AssetVersion).where(AssetVersion.package_id == 'chill-duplicate')).all()
    assert d.content_selection == ['chill-keep'] and d.config_version == version + 1
    assert d.installed_assets == {'chill-duplicate': 2}
    assert client.get('/api/v1/packages/chill-duplicate/versions/1/manifest').status_code == 404
    assert client.get('/assets?kind=chill').status_code == 200
    assert db.get(AssetPackage, 'chill-duplicate') is None
    for item in kept['files']:
        assert client.get(item['url']).status_code == 200
    assert event(client, old_plan, event='boot_success', firmwareVersion='0.8.0',
        installedAssets=old_plan['desiredAssets']).status_code == 409
    plan = sync(client, d.installed_assets)
    assert 'chill-duplicate' not in plan['desiredAssets'] and not plan['cleanupAllowed']
    response = event(client, plan, event='boot_success', firmwareVersion='0.8.0',
        installedAssets=plan['desiredAssets'])
    assert response.json()['removeVersions'] == [{'packageId': 'chill-duplicate', 'version': 2}]


def test_stale_confirmation_keeps_package_and_device_configuration(client, db):
    create(client, 'chill-stale')
    d = device(db)
    d.content_selection = ['chill-stale']
    db.commit()
    version = d.config_version
    assert client.get('/assets/chill-stale/delete').status_code == 200
    assert client.post('/assets/chill-stale/files', data={'expected': 1},
        files={'files': ('new.png', b'frame')}, follow_redirects=False).status_code == 303
    assert delete(client, 'chill-stale').status_code == 409
    assert db.get(AssetPackage, 'chill-stale').current_version == 2
    assert d.content_selection == ['chill-stale'] and d.config_version == version


def test_delete_custom_avatar_uses_builtin_fallback(client, db):
    create(client, 'avatar-duplicate', 'avatar')
    d = device(db)
    d.avatar = 'avatar-duplicate'
    db.commit()
    assert delete(client, 'avatar-duplicate').status_code == 303
    assert d.avatar == 'dragon'
    assert 'avatar-dragon' in sync(client)['desiredAssets']


def test_delete_quiz_removes_catalog_questions_and_assignments(client, db):
    db.execute(text('PRAGMA foreign_keys=ON'))
    assert db.scalar(text('PRAGMA foreign_keys')) == 1
    create(client, 'quiz-duplicate', 'quiz')
    package = db.get(AssetPackage, 'quiz-duplicate')
    catalog_id = package.catalog_id
    catalog = db.get(QuizCatalog, catalog_id)
    catalog.questions.append(QuizQuestion(question='Test?', answers=['a', 'b', 'c', 'd']))
    d = device(db)
    d.quiz_catalogs.append(catalog)
    db.commit()
    version, quiz_version = d.config_version, d.quiz_version
    assert 'alle Fragen' in client.get('/assets/quiz-duplicate/delete').text
    assert delete(client, 'quiz-duplicate').status_code == 303
    assert db.get(QuizCatalog, catalog_id) is None
    assert not d.quiz_catalogs
    assert d.config_version == version + 1 and d.quiz_version == quiz_version + 1
    assert not db.scalars(select(QuizQuestion).where(QuizQuestion.catalog_id == catalog_id)).all()
    service.ensure_packages(db)
    assert db.get(AssetPackage, 'quiz-duplicate') is None
    assert not db.scalar(select(AssetPackage).where(AssetPackage.catalog_id == catalog_id))


def test_delete_common_invalidates_configuration_for_all_devices(client, db):
    create(client, 'common-duplicate', 'common')
    d = device(db)
    version = d.config_version
    assert delete(client, 'common-duplicate').status_code == 303
    assert d.config_version == version + 1
    assert 'common-duplicate' not in sync(client)['desiredAssets']


def test_standard_packages_are_protected_and_missing_packages_return_404(client, db):
    for package_id in ['avatar-dragon', 'chill-space', 'communication-messages']:
        package = db.get(AssetPackage, package_id)
        page = client.get(f'/assets/{package_id}/delete')
        assert page.status_code == 200 and 'kann nicht gelöscht' in page.text
        assert 'name="confirmed"' not in page.text
        assert delete(client, package_id, package.current_version).status_code == 422
        assert db.get(AssetPackage, package_id) is not None
    assert client.get('/assets/missing/delete').status_code == 404
    assert delete(client, 'missing').status_code == 404
