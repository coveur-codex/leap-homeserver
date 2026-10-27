from io import BytesIO
from PIL import Image
from app.models import AssetPackage, Device
from app.services import distribution as assets, game_avatars


def png(size=(80,80),color=(20,40,60,0)):
    out=BytesIO(); Image.new('RGBA',size,color).save(out,'PNG'); return out.getvalue()


def test_generate_update_distribute(db):
    avatar=AssetPackage(id='avatar-test',name='Test',kind='avatar',current_version=0)
    db.add(avatar); db.flush()
    source=assets.store_bytes(png())
    files={'Example/data/pet/pagestatics/games.png':source,
           'data/pet/pagestatics/communication.png':assets.store_bytes(png(color=(255,0,0,255)))}
    assets.publish(db,avatar,files,{},0)
    assert game_avatars.ensure_package(db)
    p=db.get(AssetPackage,'game-avatars'); v=assets.current(db,p)
    assert v.manifest['definition']['avatarSources']['avatar-test']['image']=='avatar-test.png'
    assert assets.file_map(v)['avatar-test.png']==source
    assert not game_avatars.ensure_package(db)
    for channel in ('stable','beta'):
        d=Device(device_id=channel,name=channel,avatar='other',firmware_channel=channel,content_selection=[],communication_enabled=False)
        db.add(d); db.flush(); assert p in assets.desired_packages(db,d)
    files['Example/data/pet/pagestatics/games.png']=assets.store_bytes(png((160,160),(1,2,3,100)))
    assets.publish(db,avatar,files,{},1)
    assert game_avatars.ensure_package(db) and p.current_version==2
    info=assets.file_map(assets.current(db,p))['avatar-test.png']
    with Image.open(assets.blob_path(info['sha256'])) as image:
        assert image.size==(80,80) and image.mode=='RGBA'
    assets.publish(db,avatar,{}, {},2)
    assert game_avatars.ensure_package(db)
    assert not assets.file_map(assets.current(db,p))
