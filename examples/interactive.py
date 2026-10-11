"""Interactive test driver: JSON tool calls on stdin, image payloads never echoed."""
import json
import sys
from mcp_client import MCP

client=MCP()
try:
    print(json.dumps({'ready':True,'tools':[t['name'] for t in client.rpc('tools/list',{})['tools']]}),flush=True)
    for line in sys.stdin:
        if line.strip()=='exit':break
        try:
            command=json.loads(line);result=client.call(command['name'],command.get('arguments'))
            if isinstance(result,list):result=[{k:v for k,v in c.items() if k!='data'} for c in result]
            print(json.dumps({'ok':True,'data':result}),flush=True)
        except Exception as e:print(json.dumps({'ok':False,'error':str(e)}),flush=True)
finally:client.close()
