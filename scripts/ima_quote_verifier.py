"""Verify a pre-staged local IMA log against a fresh signed PCR10 Quote.

The log path is provisioned by the caller, never taken from a remote evidence
field. Transport/upload is intentionally a separate, still pending component.
"""
import base64
import json
from pathlib import Path
import secrets
import subprocess
from tpm_attestation import QuoteVerifier


class ImaQuoteVerifier(QuoteVerifier):
    def __init__(self,public_key,inspector,replayer,log_path):
        super().__init__(public_key,inspector,pcr_selection='sha256:10')
        self.policy_id='pinned-ak-ima-chain-v1'
        self.replayer=str(Path(replayer).resolve())
        self.log_path=str(Path(log_path).absolute())

    def verify(self,evidence,challenge):
        result=super().verify(evidence,challenge)
        result.update(ima_validity='not_evaluated',measurement_policy_validity='not_evaluated')
        if result['reason']!='SCOPED_POLICY_PASS':return result
        replay=subprocess.run([self.replayer,self.log_path],capture_output=True,text=True,timeout=5)
        if replay.returncode not in (0,1):raise OSError('IMA_REPLAYER_FAILED')
        value=json.loads(replay.stdout)
        if replay.returncode:
            if value.get('reason') in ('OPEN_ERROR','READ_ERROR','CLOCK_ERROR','TIME_LIMIT','CLOSE_ERROR'):
                raise OSError('IMA_LOG_UNAVAILABLE')
            return dict(result,reason='IMA_LOG_INVALID',policy_validity='failed',ima_validity='invalid')
        if value.get('parsed') is not True or not isinstance(value.get('replayed_pcr_sha256'),str):
            raise OSError('IMA_REPLAYER_RESULT_INVALID')
        signed_pcr=base64.b64decode(evidence['pcrs'],validate=True).hex()
        if not secrets.compare_digest(value['replayed_pcr_sha256'],signed_pcr):
            return dict(result,reason='IMA_LOG_REPLAY_MISMATCH',policy_validity='failed',ima_validity='mismatch')
        return dict(result,ima_validity='quote_bound',ima_records=value['records'])
