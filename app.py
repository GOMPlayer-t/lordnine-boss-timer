import json, sqlite3, hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

BASE=Path(__file__).resolve().parent
DB_PATH=BASE/'boss.db'
CONFIG_PATH=BASE/'config.json'
KST=ZoneInfo('Asia/Seoul')
app=FastAPI(title='곰플레이어 로드나인 보스타이머')
app.mount('/static', StaticFiles(directory=BASE/'static'), name='static')
templates=Jinja2Templates(directory=BASE/'templates')

def now(): return datetime.now(KST)
def load_config(): return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
def pin_hash(s): return hashlib.sha256(str(s).encode()).hexdigest()
def check_pin(pin, admin=False):
    c=load_config(); target=[c['admin_pin']] if admin else [c['admin_pin'],c['member_pin']]
    return pin_hash(pin) in {pin_hash(x) for x in target}
def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.execute('CREATE TABLE IF NOT EXISTS bosses(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,respawn_minutes INTEGER,weekday INTEGER,fixed_time TEXT,enabled INTEGER DEFAULT 1,created_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS cuts(id INTEGER PRIMARY KEY AUTOINCREMENT,boss_id INTEGER NOT NULL,killed_at TEXT NOT NULL,actor TEXT,created_at TEXT NOT NULL)')
    if c.execute('SELECT COUNT(*) n FROM bosses').fetchone()['n']==0:
        c.execute('INSERT INTO bosses(name,kind,respawn_minutes,created_at) VALUES(?,?,?,?)',('티토르','respawn',2580,now().isoformat()))
        c.execute('INSERT INTO bosses(name,kind,weekday,fixed_time,created_at) VALUES(?,?,?,?,?)',('클레메티스','weekly',0,'12:30',now().isoformat()))
    c.commit(); c.close()
init_db()

def next_weekly(w, hhmm, ref=None):
    ref=ref or now(); h,m=map(int,hhmm.split(':')); days=(w-ref.weekday())%7; d=(ref+timedelta(days=days)).date(); x=datetime(d.year,d.month,d.day,h,m,tzinfo=KST)
    return x if x>=ref else x+timedelta(days=7)

def state_for(r,c,ref=None):
    ref=ref or now(); last=None; nxt=None
    if r['kind']=='respawn':
        cut=c.execute('SELECT * FROM cuts WHERE boss_id=? ORDER BY killed_at DESC LIMIT 1',(r['id'],)).fetchone()
        if cut: last=datetime.fromisoformat(cut['killed_at']); nxt=last+timedelta(minutes=int(r['respawn_minutes']))
    else: nxt=next_weekly(int(r['weekday']),r['fixed_time'],ref)
    return {'id':r['id'],'name':r['name'],'kind':r['kind'],'respawn_minutes':r['respawn_minutes'],'weekday':r['weekday'],'fixed_time':r['fixed_time'],'last_cut':last.isoformat() if last else None,'next_spawn':nxt.isoformat() if nxt else None,'remain_seconds':int((nxt-ref).total_seconds()) if nxt else None}

@app.get('/',response_class=HTMLResponse)
def home(request:Request):
    return templates.TemplateResponse(request=request,name='index.html',context={'site_name':load_config()['site_name']})
@app.get('/api/state')
def state():
    c=db(); rows=c.execute('SELECT * FROM bosses WHERE enabled=1').fetchall(); out=[state_for(r,c) for r in rows]; c.close(); out.sort(key=lambda x:10**18 if x['remain_seconds'] is None else x['remain_seconds']); return {'now':now().isoformat(),'bosses':out}
@app.post('/api/cut')
def cut(boss_id:int=Form(...),killed_at:str=Form(''),actor:str=Form(''),pin:str=Form(...)):
    if not check_pin(pin): return JSONResponse({'ok':False,'message':'비밀번호가 틀렸습니다.'},403)
    c=db(); b=c.execute('SELECT * FROM bosses WHERE id=?',(boss_id,)).fetchone()
    if not b or b['kind']!='respawn': c.close(); return JSONResponse({'ok':False,'message':'컷 등록 가능한 보스가 아닙니다.'},400)
    d=now() if not killed_at.strip() else datetime.fromisoformat(killed_at).replace(tzinfo=KST)
    c.execute('INSERT INTO cuts(boss_id,killed_at,actor,created_at) VALUES(?,?,?,?)',(boss_id,d.isoformat(),actor.strip(),now().isoformat())); c.commit(); c.close(); return {'ok':True}
@app.post('/api/add')
def add(name:str=Form(...),kind:str=Form(...),respawn_hours:str=Form(''),weekday:str=Form(''),fixed_time:str=Form(''),pin:str=Form(...)):
    if not check_pin(pin,True): return JSONResponse({'ok':False,'message':'관리자 비밀번호가 틀렸습니다.'},403)
    c=db()
    try:
        if kind=='respawn': c.execute('INSERT INTO bosses(name,kind,respawn_minutes,created_at) VALUES(?,?,?,?)',(name.strip(),'respawn',round(float(respawn_hours)*60),now().isoformat()))
        else: c.execute('INSERT INTO bosses(name,kind,weekday,fixed_time,created_at) VALUES(?,?,?,?,?)',(name.strip(),'weekly',int(weekday),fixed_time,now().isoformat()))
        c.commit()
    except Exception as e: c.close(); return JSONResponse({'ok':False,'message':'입력값을 확인하세요. 같은 이름의 보스가 있을 수도 있습니다.'},400)
    c.close(); return {'ok':True}
@app.post('/api/delete')
def delete(boss_id:int=Form(...),pin:str=Form(...)):
    if not check_pin(pin,True): return JSONResponse({'ok':False,'message':'관리자 비밀번호가 틀렸습니다.'},403)
    c=db(); c.execute('DELETE FROM cuts WHERE boss_id=?',(boss_id,)); c.execute('DELETE FROM bosses WHERE id=?',(boss_id,)); c.commit(); c.close(); return {'ok':True}
