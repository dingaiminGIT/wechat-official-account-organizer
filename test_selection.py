import json,pathlib,tempfile,threading,time,urllib.request,urllib.error,unittest
from unittest.mock import patch
import selection_server as m
class SafetyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();m.DATA=pathlib.Path(self.tmp.name);m.ROOT=pathlib.Path(__file__).parent;m.STOP.clear();m.WORKER=None;m.CONNECTING=False;m.MINIAPPS_AT_BRIDGE_START=set()
  self.ident={'profile_key':'a'*64,'session_key':'s'*64,'label':'fixture'};m.CURRENT=self.ident.copy()
  self.idpatch=patch.object(m.runtime_guard,'identity',side_effect=lambda:self.ident.copy());self.idpatch.start()
  self.ready=patch.object(m,'ensure_ready',side_effect=lambda *args,**kwargs:m.verify_identity());self.ready.start()
  m.write('live-accounts-probe.json',{'profile_key':m.CURRENT['profile_key'],'capturedAt':'fixture','accounts':[{'id':x,'name':x} for x in ['a','b','w']]});m.write('whitelist.json',{'ids':['w']})
  self.calls=[];self.result={'status':'unfollowed','subscribed':False}
  def fake(i):self.calls.append(i);return self.result
  self.action=patch.object(m,'action',side_effect=fake);self.action.start()
  self.server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);m.HOST='127.0.0.1:'+str(self.server.server_port);threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def tearDown(self):
  m.STOP.set()
  if m.WORKER:m.WORKER.join(5)
  self.server.shutdown();self.server.server_close();self.action.stop();self.ready.stop();self.idpatch.stop();self.tmp.cleanup()
 def post(self,path,payload,identity=None,token=None):
  payload={**payload,**({k:self.ident[k] for k in ('profile_key','session_key')} if identity is None else identity)}
  req=urllib.request.Request('http://'+m.HOST+path,data=json.dumps(payload).encode(),headers={'Origin':'http://'+m.HOST,'Content-Type':'application/json','X-Selection-Token':m.token() if token is None else token})
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def wait(self):
  if m.WORKER:m.WORKER.join(5)
 def plan(self,ids=['a']):return self.post('/api/selection',{'ids':ids})[1]
 def test_whitelist_identity_and_csrf(self):
  self.assertEqual(self.post('/api/selection',{'ids':['a']},token='bad')[0],403)
  for ids in [['w'],['unknown'],['a','a'],[]]:self.assertEqual(self.post('/api/selection',{'ids':ids})[0],409)
  self.assertEqual(self.post('/api/selection',{'ids':['a']},identity={'profile_key':'other','session_key':'other'})[0],409)
  p=self.plan();self.post('/api/whitelist',{'ids':['w','a']});self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']})[0],409);self.assertEqual(self.calls,[])
 def test_execution_is_once_and_timed(self):
  p=self.plan();self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']})[0],200);self.wait()
  self.assertEqual(self.calls,['a']);self.assertEqual(m.job()['status'],'completed');self.assertEqual(m.job()['execution_ms'],m.job()['items'][0]['execution_ms'])
  self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']})[0],409)
 def test_incompatible_never_consumes_or_executes(self):
  p=self.plan();m.ensure_ready.side_effect=RuntimeError('unsupported version')
  self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']})[0],409);self.assertFalse(m.read('selected-accounts.json')['consumed']);self.assertEqual(self.calls,[])
 def test_account_switch_rejects_and_hides_data(self):
  p=self.plan();old=m.CURRENT.copy();self.ident={'profile_key':'b'*64,'session_key':'t'*64,'label':'other'}
  self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']},identity=old)[0],409);self.assertEqual(m.snapshot()['catalog']['accounts'],[]);self.assertEqual(self.calls,[])
 def test_accounts_have_separate_whitelists(self):
  m.CURRENT={'profile_key':'b'*64,'session_key':'t'*64};self.assertEqual(m.white(),[]);self.assertEqual(m.data()['accounts'],[]);m.write('whitelist.json',{'ids':['other']});m.CURRENT=self.ident.copy();self.assertEqual(m.white(),['w'])
 def test_detects_miniapp_opened_before_bridge(self):
  output=''' 123 /Applications/WeChat.app/Contents/MacOS/WeChat\n 456 /Applications/WeChat.app/Contents/Frameworks/WeChatAppEx Framework.framework/Helpers/WeApp.app/Contents/MacOS/WeApp --wmpf-render-type=1 --wmpf-appid=wxd45abc\n 789 /Applications/WeChat.app/Contents/Frameworks/WeChatAppEx Framework.framework/Helpers/WeApp.app/Contents/MacOS/WeApp --wmpf-render-type=4 --wmpf-appid=preload-13\n'''
  self.assertEqual(m.open_miniapp_pids(output),{456});m.MINIAPPS_AT_BRIDGE_START={456};self.assertIn('启动前打开',m.miniapp_wait_message())
 def test_unknown_result_pauses_before_next(self):
  m.action.side_effect=RuntimeError('uncertain');p=self.plan(['a','b']);self.post('/api/execute',{'plan_id':p['plan_id']});self.wait()
  self.assertEqual(m.action.call_count,1);self.assertEqual(m.job()['status'],'paused');self.assertEqual(m.job()['items'][1]['status'],'queued')
 def test_switch_during_queue_stops_following_items(self):
  def switched(i):self.calls.append(i);self.ident['session_key']='changed';return self.result
  m.action.side_effect=switched;p=self.plan(['a','b']);self.post('/api/execute',{'plan_id':p['plan_id']});self.wait();self.assertEqual(self.calls,['a']);self.assertEqual(m.job()['status'],'paused')
 def test_resume_skips_completed_and_rejects_new_session(self):
  m.write('unfollow-job.json',{'id':'resume','profile_key':m.CURRENT['profile_key'],'session_key':m.CURRENT['session_key'],'status':'paused','items':[{'id':'a','status':'unfollowed'},{'id':'b','status':'uncertain'}]})
  self.assertEqual(self.post('/api/resume',{'job_id':'resume'})[0],200);self.wait();self.assertEqual(self.calls,['b']);self.assertEqual(m.job()['status'],'completed')
  j=m.job();j.update(status='paused',session_key='old');m.write('unfollow-job.json',j);self.assertEqual(self.post('/api/resume',{'job_id':'resume'})[0],409)
 def test_concurrent_execute_is_not_duplicated(self):
  gate=threading.Event()
  def slow(i):self.calls.append(i);gate.wait(2);return self.result
  m.action.side_effect=slow;p=self.plan();responses=[]
  threads=[threading.Thread(target=lambda:responses.append(self.post('/api/execute',{'plan_id':p['plan_id']})[0])) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join()
  gate.set();self.wait();self.assertEqual(sorted(responses),[200,409]);self.assertEqual(self.calls,['a'])
 def test_serial_queue_has_no_fixed_gap_and_honors_stop(self):
  p=self.plan(['a','b'])
  with patch.object(m.STOP,'wait',side_effect=AssertionError('unexpected fixed gap')):
   self.assertEqual(self.post('/api/execute',{'plan_id':p['plan_id']})[0],200);self.wait()
  self.assertEqual(self.calls,['a','b']);self.assertEqual(m.job()['status'],'completed')
  self.calls.clear()
  def stopped(i):self.calls.append(i);m.STOP.set();return self.result
  m.action.side_effect=stopped;p=self.plan(['a','b']);self.post('/api/execute',{'plan_id':p['plan_id']});self.wait()
  self.assertEqual(self.calls,['a']);self.assertEqual(m.job()['status'],'stopped')
 def test_refollow_requires_history_and_preserves_protection(self):
  with patch.object(m.MANAGER,'call',return_value={'status':'followed','subscribed':True}) as follow:
   self.assertEqual(self.post('/api/refollow',{'id':'a','protect_after':True})[0],409);follow.assert_not_called()
   catalog=m.data();catalog['accounts'][0].update(subscribed=False,was_unfollowed=True,unfollowed_at=m.now());m.write('live-accounts-probe.json',catalog)
   self.assertEqual(self.post('/api/refollow',{'id':'a','protect_after':True})[0],200);self.wait()
   follow.assert_called_once_with('follow',m.CURRENT,'a');self.assertIn('a',m.white())
   a=m.data()['accounts'][0];self.assertTrue(a['was_unfollowed']);self.assertTrue(a['subscribed']);self.assertEqual(m.job()['status'],'completed');self.assertEqual(m.read('account-history.json')[0]['action'],'follow')
 def test_refollow_uncertain_pauses_without_claiming_recovery(self):
  catalog=m.data();catalog['accounts'][0].update(subscribed=False,was_unfollowed=True,unfollowed_at=m.now());m.write('live-accounts-probe.json',catalog)
  with patch.object(m.MANAGER,'call',side_effect=RuntimeError('uncertain')):
   self.assertEqual(self.post('/api/refollow',{'id':'a','protect_after':True})[0],200);self.wait()
   self.assertEqual(m.job()['status'],'paused');self.assertFalse(m.data()['accounts'][0]['subscribed']);self.assertNotIn('a',m.white());self.assertIsNone(m.read('account-history.json'))
 def test_retention_expires_records_but_keeps_followed_and_whitelist(self):
  at=m.parsed_date('2026-09-07T12:00:00Z');old=(at-m.datetime.timedelta(days=31)).isoformat();recent=(at-m.datetime.timedelta(days=29)).isoformat()
  m.write('live-accounts-probe.json',{'accounts':[{'id':'a','was_unfollowed':True,'subscribed':False,'unfollowed_at':old},{'id':'b','was_unfollowed':True,'subscribed':True,'unfollowed_at':old},{'id':'w','was_unfollowed':True,'subscribed':False,'unfollowed_at':recent}]})
  m.write('account-history.json',[{'id':'a','at':old},{'id':'w','at':recent}]);m.write('unfollow-job.json',{'status':'completed','finished_at':old});m.write('selected-accounts.json',{'created_at':old})
  m.prune_history(m.path('live-accounts-probe.json').parent,at)
  self.assertEqual([a['id'] for a in m.data()['accounts']],['b','w']);self.assertNotIn('was_unfollowed',m.data()['accounts'][0]);self.assertIn('history_expires_at',m.data()['accounts'][1]);self.assertEqual(m.white(),['w']);self.assertEqual(len(m.read('account-history.json')),1);self.assertIsNone(m.job());self.assertIsNone(m.read('selected-accounts.json'))
if __name__=='__main__':unittest.main()
