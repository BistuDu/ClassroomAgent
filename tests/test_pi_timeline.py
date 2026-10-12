import json
import tempfile
import unittest
from pathlib import Path
from backend.store import Store

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db.sqlite3');self.sid=self.store.session()['id'];self.n=0
    def tearDown(self):self.store.close();self.temp.cleanup()
    def pi(self,eventType,**payload):
        self.n+=1
        return self.store.pi_event(self.sid,'r1',{'seq':self.n,'capturedAt':'2026-10-06T00:00:00+00:00','payload':{'eventType':eventType,**payload}})
    def nodes(self):return self.store.timeline(self.sid)['nodes']
    def test_final_reconciliation_receipts_and_duplicate_delivery(self):
        self.pi('message_start',messageId='u',role='user',message={'content':[{'type':'text','text':'我的需求'}]})
        self.pi('message_update',messageId='a',updateType='text_delta',contentIndex=0,delta='第一')
        self.pi('message_end',messageId='a',role='assistant',content=[{'type':'text','text':'第一段完整文字'}],stopReason='stop')
        self.pi('tool_execution_start',messageId='a',toolCallId='call',toolName='fetch_url',args={'url':'https://example.org'})
        self.pi('tool_execution_end',messageId='a',toolCallId='call',toolName='fetch_url',isError=True,result={'content':[{'type':'text','text':'参数被 SDK 拒绝'}]})
        self.pi('message_end',role='toolResult',toolCallId='call')
        self.store.pi_event(self.sid,'r1',{'seq':self.n,'capturedAt':'x','payload':{'eventType':'message_start'}})
        nodes=self.nodes();self.assertEqual(len(nodes),3)
        self.assertEqual(nodes[1]['data']['text'],'第一段完整文字');self.assertEqual(nodes[2]['status'],'failed')
        self.assertIsNone(self.store.cached_call('r1','call'))
        detail=self.store.get('pi_tool_detail',self.sid+':r1:call')
        self.assertEqual(detail['result']['content'][0]['text'],'参数被 SDK 拒绝');self.assertEqual(detail['parameters']['url'],'https://example.org')
        self.assertEqual({n['source'] for n in nodes},{'pi'})
    def test_business_events_do_not_create_agent_facts_and_interruption_keeps_receipt(self):
        self.store.event(self.sid,'tool_parameters',{'name':'fake','requestId':'x'})
        self.store.event(self.sid,'tool_finished',{'name':'fake','requestId':'x','failed':False})
        self.store.event(self.sid,'user_operation',{'operationId':'manual','status':'completed'})
        self.assertEqual(self.nodes(),[])
        self.pi('tool_execution_start',toolCallId='real',toolName='generate_tts',args={'sceneId':'s1'})
        self.store.event(self.sid,'run_failed',{'runId':'r1','error':'进程退出'})
        node=self.nodes()[0];self.assertEqual(node['status'],'interrupted');self.assertEqual(node['data']['sdkStatus'],'running')
        self.assertIsNone(self.store.get('pi_tool_detail',self.sid+':r1:real')['result'])
    def test_question_from_sdk_only_and_late_progress_is_ignored(self):
        question={'id':'q1','question':'确认方案？','kind':'question','options':['继续']}
        self.store.event(self.sid,'question',question);self.assertEqual(self.nodes(),[])
        self.pi('tool_execution_start',toolName='ask_user',toolCallId='ask',args={'kind':'question','question':'确认方案？'})
        self.pi('tool_execution_end',toolName='ask_user',toolCallId='ask',isError=False,result={'content':[{'type':'text','text':'等待用户'}],'details':{'status':'completed','data':question}})
        self.store.event(self.sid,'question_answered',{'questionId':'q1','answer':'继续'})
        self.pi('tool_execution_update',toolName='ask_user',toolCallId='ask',partialResult={'details':{'late':True}})
        nodes=self.nodes();self.assertEqual(len(nodes),2);self.assertEqual(nodes[0]['status'],'completed');self.assertEqual(nodes[1]['status'],'answered');self.assertNotIn('progress',nodes[0]['data'])
        events=self.store.events(self.sid);self.assertTrue(any(e['source']=='pi' for e in events));self.assertTrue(any(e['source']=='workbench' for e in events))
    def test_legacy_remains_readable_but_cannot_supply_new_receipt(self):
        self.store.event(self.sid,'tool_finished',{'runId':'old','name':'read_stage','requestId':'oldcall'},source='legacy',version=1)
        self.store.cache_call('old','oldcall',{'ok':True,'data':['old']})
        self.pi('tool_execution_end',toolName='read_stage',toolCallId='newcall',isError=False,result={'content':[{'type':'text','text':'new'}]})
        nodes=self.nodes();self.assertEqual([n['source'] for n in nodes],['legacy','pi'])
        self.assertEqual(self.store.get('pi_tool_detail',self.sid+':r1:newcall')['result']['content'][0]['text'],'new')

    def test_thinking_stream_reconciles_final_text_and_survives_refresh(self):
        self.pi('message_update',messageId='a',updateType='thinking_start',contentIndex=0,textAvailable=True)
        self.pi('message_update',messageId='a',updateType='thinking_delta',contentIndex=0,delta='先核对')
        self.pi('message_update',messageId='a',updateType='thinking_delta',contentIndex=0,delta='目标')
        self.assertEqual(self.nodes()[0]['data']['text'],'先核对目标')
        self.pi('message_update',messageId='a',updateType='thinking_end',contentIndex=0,text='先核对目标，再选择工具。')
        self.pi('message_end',messageId='a',role='assistant',content=[{'type':'thinking','thinking':'先核对目标，再选择工具。'},{'type':'text','text':'我先看看课程。'}],stopReason='stop')
        self.assertEqual([n['kind'] for n in self.nodes()],['reasoning','assistant'])
        self.assertEqual(self.nodes()[0]['data']['text'],'先核对目标，再选择工具。')
        self.assertEqual(self.nodes()[0]['status'],'completed')
        self.store.close();self.store=Store(Path(self.temp.name)/'db.sqlite3')
        self.assertEqual(self.nodes()[0]['data']['text'],'先核对目标，再选择工具。')

if __name__=='__main__':unittest.main()
