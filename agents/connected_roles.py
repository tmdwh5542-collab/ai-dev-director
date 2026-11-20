"""Shared role prompts with explicit registered transport and truthful provenance."""
import json
import tempfile
from datetime import datetime, timezone
from agents.google_roles import GoogleReviewer
from core.bootstrap import prepare_project
from core.research_runner import EvidenceOnlyRunner as TriadResearchRunner
from schemas.provenance import AgentProvenanceRecord

class ConnectedHead(GoogleReviewer):
    usage_role='HEAD'
    def __init__(self,domain,**kwargs):
        from core.env_utils import resolve_cli
        from core.ai_connections import CLI
        executable=resolve_cli(CLI[domain]);kwargs['executable']=executable
        super().__init__(**kwargs);self.executable=executable;self.domain=domain;self.provider=domain.lower();self.agent_family=domain.lower();self.last_call=None
    def _invoke_cli(self,prompt,cwd=None):
        from core import usage
        usage.set_context(role=self.usage_role)
        with tempfile.TemporaryDirectory(prefix='director-connected-') as tmp:
            prepare_project(tmp);result=TriadResearchRunner(timeout=self.timeout,no_output_timeout=self.no_progress_timeout).invoke(self.domain,'Use supplied evidence only. Do not use tools.\n'+prompt,tmp,self.usage_role)
        self.last_call=result
        output=result['output']
        if self.domain=='ANTHROPIC' and not result.get('api_key_used'):
            try:
                envelope=json.loads(output)
                if isinstance(envelope,dict) and isinstance(envelope.get('result'),str): output=envelope['result']
            except ValueError: pass
        return output
    def get_provenance(self,exit_code=0):
        r=self.last_call or {};api=r.get('api_key_used',False)
        return AgentProvenanceRecord(agent=self.usage_role,provider=self.provider,runtime=self.domain.lower()+('-api' if api else '-cli'),model=self.model,executable=r.get('executable','uninvoked'),version=r.get('version','unknown'),invocation_command=r.get('invocation','uninvoked'),exit_code=r.get('exit_code'),http_status=r.get('http_status'),duration_sec=r.get('duration_sec'),authentication_mode='api_key' if api else 'subscription',api_key_policy='explicit_opt_in' if api else 'disabled',api_key_used=api,observed_fields=r.get('observed_fields',['executable','version','exit_code','duration_sec','invocation_command']),timestamp=datetime.now(timezone.utc).isoformat())

class ConnectedReviewer(ConnectedHead):
    usage_role='REVIEWER'
