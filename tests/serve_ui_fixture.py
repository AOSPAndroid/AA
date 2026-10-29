"""Local UI fixture; never executes WMI, PsTools or deploys software."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import sys,tempfile,sqlite3,json,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import main as m
from backend import atlas_store as store
import uvicorn
# All collector control routes in this fixture are simulated, including setup.
from backend.inbox import inbox_control
fixture_control = dict(configured=True, state='running', agent_running=True, pending=False,
                       mail_user='EXAMPLE\\MailUser', atlas_user='EXAMPLE\\AtlasAdmin', directory='C:\\Example\\Inbox',
                       desired=dict(running=True, outlook=True, notifications=True, outlook_previews=False))
def fixture_command(self, action, **preferences):
 if action == 'source' and not fixture_control['desired']['running']:
  fixture_control['desired'].update(outlook=False, notifications=False)
 fixture_control['desired'].update(preferences)
 if action in ('start', 'stop'):
  fixture_control['desired']['running'] = action == 'start'
  fixture_control['state'] = 'running' if action == 'start' else 'stopped'
 if action == 'source':
  fixture_control['desired']['running'] = fixture_control['desired']['outlook'] or fixture_control['desired']['notifications']
  fixture_control['state'] = 'running' if fixture_control['desired']['running'] else 'stopped'
 fixture_control['agent_running'] = fixture_control['desired']['running']
 return fixture_control
inbox_control.InboxIntegration.status=lambda self:fixture_control
inbox_control.InboxIntegration.command=fixture_command
inbox_control.InboxIntegration.configure=lambda self,*args:fixture_control
with tempfile.TemporaryDirectory() as tmp:
 base=Path(tmp);db=base/'fixture.db';a=sqlite3.connect(m.MASTER_DB);b=sqlite3.connect(db);a.backup(b);a.close();b.close()
 m.MASTER_DB=m.DB=m.HISTORY_DB=store.DB=db
 from backend.inbox import clipboard_history
 if clipboard_history.history: clipboard_history.history._path=base/'clipboard-history.json'
 m.persona_store.path=base/'personas.json';m.persona_access_store.path=base/'persona-access.json';m.joiner_store.path=base/'joiners.json'
 from backend.companion import companion_server
 if companion_server.companion:
  companion_server.companion._state_path=base/'companion-state.json';companion_server.companion._inbox=base/'companion-inbox';companion_server.companion.state={}
 if '--inbox' in sys.argv:
  from backend.inbox.outlook_watcher import MailQueue, stamp, utcnow
  from backend.directory.identity_links import rebuild_links
  from backend.inbox import mail_inbox
  os.environ['ATLAS_MAIL_DIR']=str(base/'mail')
  with sqlite3.connect(db) as c:
   uid=c.execute('select coalesce(max(id),0)+1 from users').fetchone()[0]
   for offset,name,email in [(0,'Alex Morgan','alex@example.test'),(1,'Sam Green','sam@example.test'),(2,'Sam Green','other.sam@example.test'),(3,'Marie Dupont','marie@example.test')]:
    c.execute('insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm,department,location) values(?,?,?,?,?,?,?,?,?,?)',(uid+offset,'fixture:'+str(offset),'INBOX'+str(offset),'inbox'+str(offset),name,name.lower(),email,email,'Client Services','Paris'))
   mid=c.execute('select coalesce(max(id),0)+1 from machines').fetchone()[0]
   c.execute('insert into machines(id,machine_name,machine_name_norm,assigned_to,model_id,operational_status) values(?,?,?,?,?,?)',(mid,'EXAMPLE-LAPTOP-01','example-laptop-01','INBOX0','Latitude 7450','Operational'))
   c.execute('insert into machines(id,machine_name,machine_name_norm,last_logon_user,model_id,operational_status) values(?,?,?,?,?,?)',(mid+1,'EXAMPLE-DESKTOP-02','example-desktop-02','INBOX0','OptiPlex 7020','Operational'))
   c.execute('insert into machines(id,machine_name,machine_name_norm,assigned_to,model_id,operational_status) values(?,?,?,?,?,?)',(mid+2,'EXAMPLE-LAPTOP-07','example-laptop-07','INBOX3','Latitude 5440','Operational'))
   rebuild_links(c)
   c.execute('delete from assignments where user_id_ref in (?,?,?,?)',(uid,uid+1,uid+2,uid+3))
   c.execute('insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(?,?,?,?)',(uid+3,mid+2,'assigned_to','INBOX3'))
   c.execute('insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(?,?,?,?)',(uid,mid,'assigned_to','INBOX0'))
   c.execute('insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(?,?,?,?)',(uid,mid+1,'last_logon_user','INBOX0'))
  queue=MailQueue(base/'mail',utcnow())
  for eid,name,email,subject,body in [('1','Unknown Sender','unknown@example.test','Printer on floor 3','The printer reports a paper jam.'),('2','Sam Green','unlisted@example.test','Teams audio is cutting out','My microphone disconnects during calls.'),('3','Alex Morgan','alex@example.test','VPN will not connect after the update','Hi IT,\n\nMy laptop cannot connect to VPN this morning. I restarted it, but the connection still times out.\n\nCould you help?\nAlex\n\nFICTIONAL TEST MESSAGE'),('5','Alex Morgan','alex@example.test','Software request','Hello,\n\nCould you please install Example App on my PC?\n\nThanks, Alex\n\nFICTIONAL TEST MESSAGE'),('6','Alex Morgan','alex@example.test','PC very slow','Hi,\n\nEXAMPLE-DESKTOP-02 is very slow and Outlook freezes all the time.\n\nFICTIONAL TEST MESSAGE'),('7','Alex Morgan','alex@example.test','Visio for a new joiner','Hello,\n\nDUPONT Marie joined my team on Monday. Could you install Example App on her laptop and give her the same access as me?\nSam Green said her Outlook also asks for a password.\n\nThanks, Alex Morgan\n\nFICTIONAL TEST MESSAGE')]:
   queue.insert('fixture',dict(entry_id=eid,received_at=stamp(utcnow()),conversation_id=eid,sender_name=name,sender_address=email,subject=subject,body=body,body_truncated=0))
  queue.close()
  mail_inbox.watcher_status=lambda directory:dict(state='watching' if fixture_control['desired']['running'] and fixture_control['desired']['outlook'] else 'stopped',running=fixture_control['desired']['running'] and fixture_control['desired']['outlook'],stale=False,interval=15,last_success_at=stamp(utcnow()),config={'mailbox':'Fictional test inbox'},detail='Fictional messages used for UI verification; no mailbox is connected.')
  if '--notifications' in sys.argv:
   with sqlite3.connect(base/'mail'/'inbox.sqlite3') as c:
    c.execute("insert into messages(source,entry_id,received_at,imported_at,conversation_id,sender_name,sender_address,subject,body,body_truncated,channel,content_kind,app_name) values('notification:fixture','4',?,?,'','Alex Morgan','','Alex Morgan',?,0,'teams','notification','Microsoft Teams')",(stamp(utcnow()),stamp(utcnow()),'My laptop keeps disconnecting from Wi-Fi. Could you check it?\n\nFICTIONAL TEAMS NOTIFICATION'))
   mail_inbox.notification_status=lambda directory:dict(state='watching' if fixture_control['desired']['running'] and fixture_control['desired']['notifications'] else 'stopped',running=fixture_control['desired']['running'] and fixture_control['desired']['notifications'],stale=False,last_success_at=stamp(utcnow()),teams_seen=1,captured=1,detail='Fictional notification fixture; no Teams account is connected.')
 m.REPO=base/'repo';m.REPO.mkdir();(m.REPO/'Example App').mkdir();(m.REPO/'Example App'/'setup_i.ps1').write_text('exit 0')
 m.identity=lambda:'LOCAL UI TEST'
 m.run=lambda *a,**k:type('Result',(),{'stdout':'TEST','stderr':'','returncode':0})()
 m.ps=lambda *a,**k:'True'
 if '--inbox' in sys.argv:
  # Fictional screen reading: no screenshot, OCR or clipboard access.
  from backend.inbox import screen_reader
  screen_reader.windows=lambda:True
  plain_ps=m.ps
  def fake_ps(script,*a,**k):
   if not script.startswith('$Mode='):return plain_ps(script,*a,**k)
   mode=script.split("'")[1]
   text='EXAMPLE-LAPTOP-01' if mode=='clipboard' else 'Alex Morgan 09:41\nHi, my laptop is very slow since this morning and Outlook keeps freezing.\nalex@example.test\nFICTIONAL SCREEN TEXT'
   return json.dumps(dict(source=mode,title='Chat | Alex Morgan | Microsoft Teams',process='ms-teams',text=text,lines=4,language='en-GB'))
  m.ps=fake_ps
 from backend.remote import psexec_runner as px
 def fake_pstools(args,**options):
  assert args.count('-accepteula')==1,'The selected tool must receive EULA acceptance'
  script='import json; print("SIMULATED PSTOOLS LAUNCH"); print('+repr(json.dumps(args))+')'
  return subprocess.Popen([sys.executable,'-u','-c',script],**options)
 px.runner=px.Runner(popen=fake_pstools,preflight=lambda path:dict(exists=True,elevated=True,account='TEST\\Operator'))
 def fake_worker(j,p):
  m.emit(j,'Simulated installer reported exit code 0','complete',exit_code='0');m.history_update(j,state='complete',exit_code='0')
 m.deploy_worker=fake_worker
 uvicorn.run(m.app,host='127.0.0.1',port=8892,log_level='error')
