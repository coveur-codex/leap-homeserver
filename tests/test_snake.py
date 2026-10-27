import random
import pytest
from app.services.snake import Room, STEP, DURATION


def playing(n=2):
    r=Room(0,random.Random(7))
    for i in range(n):
        r.join(str(i),'avatar-dragon','#ff9900',i)
        r.players[str(i)].seen=9999
    r.advance(10000); assert r.phase=='countdown'
    r.advance(13000); assert r.phase=='playing'
    for p in r.players.values(): p.seen=13000
    return r


@pytest.mark.parametrize('n,fruits,target',[(2,6,20),(3,8,30),(4,10,40)])
def test_rules_and_time(n,fruits,target):
    r=playing(n)
    assert (len(r.food),r.target)==(fruits,target)
    assert len(set(c for p in r.players.values() for c in p.body))==n*3
    r.score=target+1
    r.advance(13000+DURATION-1); assert r.phase=='playing'
    r.advance(13000+DURATION)
    assert r.phase=='finished' and r.snapshot(133000)['remainingMs']==0
    assert r.score>=target+1 and r.tick==DURATION//STEP


def test_lobby_deadline_capacity_and_reconnect():
    r=Room(0); r.join('a','avatar-frog','#123456',0)
    r.join('b','avatar-frog','#123456',9000); r.players['a'].seen=9999
    assert r.start==13000
    r.advance(9999); assert r.phase=='lobby'
    r.advance(10000); assert r.phase=='countdown'
    with pytest.raises(ValueError): r.join('c','','',10000)
    r.disconnect('a',10001)
    assert r.join('a','','',10002).avatar=='avatar-frog'
    full=Room(0)
    for i in range(4): full.join(str(i),'','',0)
    with pytest.raises(ValueError): full.join('fifth','','',1)
    alone=Room(0); alone.join('a','','',0); alone.players['a'].seen=9999
    alone.advance(10000); assert alone.phase=='alone'


def test_input_dedup_late_reverse_one_turn():
    r=playing(); p=r.players['0']
    r.input('0',{'type':'input','seq':1,'tick':0,'direction':3},13000)
    assert p.queued is None  # Repeated straight input must not consume the turn.
    r.input('0',{'type':'input','seq':2,'tick':0,'direction':2},13001)
    assert p.queued is None
    r.input('0',{'type':'input','seq':3,'tick':0,'direction':0},13002)
    r.input('0',{'type':'input','seq':4,'tick':0,'direction':1},13003)
    assert p.queued==0
    p.queued=None; r.tick=8
    for seq,tick in [(5,0),(6,10),(6,8)]:
        r.input('0',{'type':'input','seq':seq,'tick':tick,'direction':1},13004)
    assert p.queued is None
    with pytest.raises(ValueError): r.input('0',{'type':'input','seq':True,'tick':8,'direction':0},13005)


def collision_room():
    r=playing(4)
    for p in r.players.values(): p.body=[]; p.protected=0; p.respawn=999999; p.seen=14000
    r.food.clear(); return r


def test_simultaneous_heads_swaps_three_way_stop():
    r=collision_room(); a,b,c,d=r.players.values()
    a.body=[(5,5),(4,5),(3,5)]; a.direction=3
    b.body=[(7,5),(8,5),(9,5)]; b.direction=2
    c.body=[(6,4),(6,3),(6,2)]; c.direction=1
    r.move(14000)
    assert [p.body[0] for p in (a,b,c)]==[(5,5),(7,5),(6,4)]
    b.body=[(6,5),(7,5),(8,5)]; r.move(14450)
    assert a.body[0]==(5,5) and b.body[0]==(6,5) and r.score==0


def test_wall_self_respawn_protection():
    r=collision_room(); a=r.players['0']
    a.body=[(39,5),(38,5),(37,5)]; a.direction=3
    r.move(14000); assert a.body==[] and a.respawn==17000
    a.seen=16999; r.move(16999); assert not a.body
    r.move(17000); assert len(a.body)==3 and a.protected==17900
    a.body=[(39,5),(38,5),(37,5)]; r.move(17450)
    assert a.body[0]==(39,5)
    a.protected=0; a.direction=1
    a.body=[(5,5),(6,5),(6,6),(5,6),(4,6)]
    r.move(17900); assert not a.body


def test_disconnect_freezes_removes_and_rejoins_same_player():
    r=playing(3); a=r.players['0']; before=list(a.body)
    r.disconnect(a.id,13001); r.move(13450); assert a.body==before
    r.move(28000); assert not a.body
    assert r.target==30 and r.food_count==8
    p=r.join(a.id,'ignored','ignored',28001)
    assert len(r.players)==3 and p.avatar=='avatar-dragon'
    r.input(a.id,{'type':'ping'},30001); r.move(31000); assert p.body


def test_food_replenishment_and_invariants():
    r=playing(4); p=r.players['0']; head=p.body[0]
    r.food={(head[0]+1,head[1])}; r.move(13450)
    assert r.score==1 and len(p.body)==4 and len(r.food)==10
    for step in range(1000):
        for p in r.players.values(): p.seen=14000+step*STEP; p.queued=r.rng.randrange(4)
        r.move(14000+step*STEP)
        cells=[c for p in r.players.values() for c in p.body]
        assert len(cells)==len(set(cells))
        assert all(0<=x<40 and 0<=y<13 for x,y in cells)
        assert not r.food.intersection(cells)


def test_respawn_deadline_between_fixed_steps():
    r=playing(); p=r.players['0']
    p.body=[]; p.respawn=16000
    # Next movement is 16150; the player reappears at 16000, not 16150.
    r.next_step=16150; p.seen=15999
    r.advance(15999); assert not p.body
    r.advance(16000); assert len(p.body)==3 and p.protected==16900
    assert r.tick==0


def test_no_fruit_inside_sealed_body():
    r=collision_room(); p=r.players['0']
    # A closed occupied ring makes its centre unreachable from any head.
    p.body=[(x,y) for y in range(4,7) for x in range(4,7) if (x,y)!=(5,5)]
    r.food_count=10
    for _ in range(100):
        r.food.clear(); r.refill(); assert (5,5) not in r.food


def test_queued_snapshot_cannot_change_with_next_move():
    r=playing(); snapshot=r.snapshot(13000)
    before=list(snapshot['players'][0]['body'])
    r.move(13450)
    assert snapshot['players'][0]['body']==before
    assert r.players['0'].body!=before
