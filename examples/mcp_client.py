"""Small stdio client for the examples. Never prints keys or arbitrary JSFL."""
import json
import os
from pathlib import Path
import subprocess
import sys

class MCP:
    def __init__(self):
        self.id=0
        root=Path(__file__).resolve().parents[1]
        self.process=subprocess.Popen([sys.executable,str(root/'mcp/launch.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1,env=dict(os.environ))
        self.rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'animation-example','version':'1.3.0'}})
    def rpc(self,method,params):
        self.id+=1
        self.process.stdin.write(json.dumps(dict(jsonrpc='2.0',id=self.id,method=method,params=params))+'\n');self.process.stdin.flush()
        line=self.process.stdout.readline()
        if not line:raise RuntimeError('MCP exited')
        reply=json.loads(line)
        if reply.get('id')!=self.id or 'error' in reply:raise RuntimeError('Invalid MCP response')
        return reply['result']
    def call(self,name,args=None):
        result=self.rpc('tools/call',{'name':name,'arguments':args or {}})
        if result.get('isError'):raise RuntimeError(' '.join(c.get('text','') for c in result['content']))
        content=result['content']
        if len(content)==1 and content[0]['type']=='text':return json.loads(content[0]['text'])
        return content
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
