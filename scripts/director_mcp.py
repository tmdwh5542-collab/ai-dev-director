"""Minimal MCP stdio reference adapter; one chosen project + employee per client.
Example: python scripts/director_mcp.py --project C:/work/game --staff planner
JSON-RPC output only; no credentials, package installs, commands or project writes. GitHub acquire writes only the bounded reference cache.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import employee_tools as tools,web_workspace as web

def dispatch(message,project,staff):
    method=message.get('method');params=message.get('params') or {}
    if method=='initialize':return {'protocolVersion':'2024-11-05','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'ai-dev-director-readonly','version':'1.0.0'}}
    if method=='ping':return {}
    if method=='tools/list':
        specs=[]
        for name in tools.allowed(staff):
            props={'path':{'type':'string'}} if name=='project_read' else {'repo':{'type':'string'},'file':{'type':'string'},'ref':{'type':'string'}} if name in ('github_read','github_acquire') else {'query':{'type':'string'}} if name=='github_search' else {}
            specs.append({'name':name,'description':tools.CATALOG[name]['description'],'inputSchema':{'type':'object','properties':props,'additionalProperties':False,'required':['path'] if name=='project_read' else ['repo','file'] if name=='github_acquire' else ['repo'] if name=='github_read' else ['query'] if name=='github_search' else []},'annotations':{'readOnlyHint':name!='github_acquire','destructiveHint':False}})
        return {'tools':specs}
    if method=='tools/call':
        try:
            args=params.get('arguments') or {}
            if 'project_path' in args:raise ValueError('프로젝트 범위는 MCP 시작 인수로 고정됩니다.')
            value=tools.invoke(staff,params.get('name'),{**args,'project_path':project})
            return {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
        except Exception as exc:return {'content':[{'type':'text','text':str(exc)[:1000]}],'isError':True}
    raise ValueError('지원하지 않는 MCP 메서드입니다.')

def main():
    if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--staff',required=True);args=parser.parse_args();project=str(web.project(args.project));tools.member(args.staff)
    for line in sys.stdin:
        try:
            if len(line)>64000:raise ValueError('요청 크기를 초과했습니다.')
            message=json.loads(line)
            if 'id' not in message:continue
            result=dispatch(message,project,args.staff);answer={'jsonrpc':'2.0','id':message['id'],'result':result}
        except Exception as exc:answer={'jsonrpc':'2.0','id':message.get('id') if isinstance(locals().get('message'),dict) else None,'error':{'code':-32602,'message':str(exc)[:500]}}
        print(json.dumps(answer,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
