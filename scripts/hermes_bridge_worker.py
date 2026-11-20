"""Run with Hermes' own Python (-I); never install/import Hermes into the Director environment.
Protocol is deliberately ours. No CLI gateway/daemon, profile reuse, tools, or fallback providers.
"""
import argparse
import contextlib
import importlib.metadata
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import sys
import threading
import time

PROTOCOL = 'director-hermes-sdk-v1'
REQUIRED = {'provider','model','api_key','base_url','enabled_toolsets','skip_context_files','skip_memory',
            'skip_background_review','max_iterations','max_tokens','capabilities'}
MESSAGES = {'SDK_MISSING':'선택한 Python 환경에 Hermes Agent가 설치되지 않았습니다.',
            'SDK_INCOMPATIBLE':'Hermes SDK 버전이 연동에 필요한 기능을 지원하지 않습니다.',
            'AUTH':'Hermes의 API 키 또는 모델 접근 권한을 확인하세요.',
            'QUOTA':'Hermes에 연결한 AI의 사용 한도·결제 상태를 확인하세요.',
            'INCOMPLETE':'Hermes가 완성된 보고서를 반환하지 않았습니다.',
            'RUNTIME':'Hermes 실행에 실패했습니다. 설치 환경·모델·연결 상태를 확인하세요.'}


def emit(value):
    print(json.dumps({'protocol':PROTOCOL,**value},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true')
    parser.add_argument('--sdk-root');parser.add_argument('--request');parser.add_argument('--job-id');parser.add_argument('--parent-pid',type=int)
    args=parser.parse_args()
    # Set before ANY Hermes import: personal hooks, plugins, MCP, profiles and rules are not loaded.
    os.environ.update(HERMES_SAFE_MODE='1',HERMES_IGNORE_USER_CONFIG='1',HERMES_IGNORE_RULES='1',
                      HERMES_YOLO_MODE='0',HF_HUB_OFFLINE='1')
    if args.sdk_root:
        sdk=Path(args.sdk_root).resolve()
        if not (sdk/'run_agent.py').is_file():emit({'ok':False,'error_code':'SDK_MISSING','error':MESSAGES['SDK_MISSING']});return 2
        sys.path.insert(0,str(sdk))
    agent=None
    try:
        if importlib.util.find_spec('run_agent') is None:
            emit({'ok':False,'error_code':'SDK_MISSING','error':MESSAGES['SDK_MISSING']});return 2
        # Suppress SDK diagnostics, not our JSON protocol. Exceptions never echo keys/provider bodies.
        with open(os.devnull,'w',encoding='utf-8') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
            from run_agent import AIAgent
            from tools.hosted_tool_policy import HOST_FEATURES
            params=inspect.signature(AIAgent).parameters
            compatible=REQUIRED<=set(params)
            try: version=importlib.metadata.version('hermes-agent')
            except importlib.metadata.PackageNotFoundError: version='source-checkout'
            if args.probe:
                result={'ok':compatible,'version':version,'python':sys.version.split()[0],
                        'error':None if compatible else MESSAGES['SDK_INCOMPATIBLE']}
            elif not compatible:
                result={'ok':False,'error_code':'SDK_INCOMPATIBLE','error':MESSAGES['SDK_INCOMPATIBLE']}
            else:
                if os.environ.get('DIRECTOR_TESTING')=='1' and os.environ.get('DIRECTOR_HERMES_BRIDGE_STUB')!='1':
                    raise RuntimeError('Live Hermes disabled during unit tests')
                request=json.loads(Path(args.request).read_text(encoding='utf-8'))
                if args.parent_pid:
                    import psutil
                    parent=psutil.Process(args.parent_pid);created=parent.create_time()
                    def watch_parent():
                        while True:
                            time.sleep(1)
                            try: alive=psutil.Process(args.parent_pid).create_time()==created
                            except psutil.Error: alive=False
                            if not alive: os._exit(130)
                    threading.Thread(target=watch_parent,daemon=True).start()
                secret=os.environ.get('DIRECTOR_HERMES_API_KEY','')
                if not secret: raise RuntimeError('Missing selected API key')
                # SDK capabilities are a second barrier, in addition to an explicit empty toolset.
                agent=AIAgent(provider=request['provider'],model=request['model'],api_key=secret,
                    base_url=request['base_url'],enabled_toolsets=[],disabled_toolsets=['all'],
                    skip_context_files=True,load_soul_identity=False,skip_memory=True,skip_background_review=True,
                    capabilities={feature:False for feature in HOST_FEATURES},
                    max_iterations=1,max_tokens=4096,run_budget_seconds=request['timeout'],
                    quiet_mode=True,save_trajectories=False,checkpoints_enabled=False,
                    fallback_model=None,credential_pool=None,platform='director-advisory',cwd=str(Path.cwd()))
                # Reject a runtime which ignores the empty-tool contract before any model call.
                if getattr(agent,'tools',None):
                    result={'ok':False,'error_code':'SDK_INCOMPATIBLE','error':MESSAGES['SDK_INCOMPATIBLE']}
                else:
                    output=agent.run_conversation(request['prompt'])
                    if not output.get('completed') or output.get('partial') or output.get('interrupted'):
                        result={'ok':False,'error_code':'INCOMPLETE','error':MESSAGES['INCOMPLETE']}
                    else:
                        text=output.get('final_response')
                        if not isinstance(text,str) or not text.strip() or len(text)>20000:
                            result={'ok':False,'error_code':'INCOMPLETE','error':MESSAGES['INCOMPLETE']}
                        else:
                            result={'ok':True,'version':version,'text':text.replace(secret,'[REDACTED]'),
                                'usage':{k:output.get(k) for k in ('api_calls','input_tokens','output_tokens','total_tokens')
                                         if type(output.get(k)) is int and output[k]>=0}}
                if agent is not None:
                    try: agent.close()
                    except Exception: pass
        emit(result);return 0 if result.get('ok') else 2
    except Exception as exc:
        name=type(exc).__name__
        code='SDK_MISSING' if isinstance(exc,ImportError) else 'AUTH' if name in {'AuthenticationError','PermissionDeniedError'} else 'QUOTA' if name=='RateLimitError' else 'RUNTIME'
        emit({'ok':False,'error_code':code,'error':MESSAGES[code]});return 2


if __name__=='__main__':sys.exit(main())
