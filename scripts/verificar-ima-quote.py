"""Offline signed PCR10/IMA fixtures. Does not exercise a physical TPM or upload."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from ima_quote_verifier import ImaQuoteVerifier
from tpm_attestation import AttestationServer


def module(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspector',type=Path,default=Path('build-tpm/lab_quote_inspect'))
    parser.add_argument('--replayer',type=Path,default=Path('build-tpm/lab_ima_replay'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();report={'passed':False,'scope':'software-signed PCR10 plus IMA fixtures; no hardware or remote upload','cases':[]}
    try:
        fixtures=module('quote_fixtures','verificar-atestacion.py');ima=module('ima_fixtures','verificar-ima.py')
        with tempfile.TemporaryDirectory(prefix='lab-ima-quote-') as temp:
            folder=Path(temp);log=folder/'ima.log'
            fixtures.command(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(folder/'private.pem')])
            fixtures.command(['openssl','pkey','-in',str(folder/'private.pem'),'-pubout','-out',str(folder/'ak.pem')])
            first,d1=ima.record();second,d2=ima.record(b'second');log.write_bytes(first+second)
            pcr=hashlib.sha256(hashlib.sha256(bytes(32)+d1).digest()+d2).digest()
            verifier=ImaQuoteVerifier(folder/'ak.pem',args.inspector,args.replayer,log)
            server=AttestationServer(verifier)
            def attempt(data,nonce=None,selection=b'\0\4\0'):
                log.write_bytes(data);challenge=server.issue('client')
                assert challenge['requested_evidence']==['tpm_quote','sha256:10']
                evidence=fixtures.fixture(challenge,folder,pcrs=pcr,nonce=nonce,selection=selection)
                return server.submit('client',evidence),evidence
            result,evidence=attempt(first+second)
            assert result['decision']=='ALLOW' and result['ima_validity']=='quote_bound' and result['ima_records']==2,result
            assert result['tpm_identity_validity']=='not_proven' and result['measurement_policy_validity']=='not_evaluated'
            assert server.submit('client',evidence)['reasons']==['CHALLENGE_REUSED']
            report['cases'].append('signed_pcr10_log_binding_and_one_use_challenge')
            for data in [first,second+first,first+second+second]:
                result,_=attempt(data)
                assert result['decision']=='DENY' and result['reasons']==['IMA_LOG_REPLAY_MISMATCH'],result
                assert result['cryptographic_validity']=='verified' and result['freshness_validity']=='verified'
            report['cases'].append('valid_signed_quote_rejects_deleted_reordered_duplicated_log')
            result,_=attempt(first[:-1]);assert result['reasons']==['IMA_LOG_INVALID'],result
            result,_=attempt(first+second,nonce='00'*32);assert result['reasons']==['NONCE_MISMATCH'],result
            result,_=attempt(first+second,selection=b'\0\2\0');assert result['decision']=='DENY',result
            report['cases'].append('truncation_nonce_and_wrong_signed_selection_rejected')
            challenge=server.issue('client');evidence=fixtures.fixture(challenge,folder,pcrs=pcr,selection=b'\0\4\0')
            try:server.submit('client',dict(evidence,log_path='/untrusted'));raise AssertionError('remote path accepted')
            except ValueError:pass
            log.unlink();result=server.submit('client',evidence)
            assert result['decision']=='INDETERMINATE' and result['reasons']==['VERIFIER_ERROR'],result
            log.write_bytes(first+second);alias=folder/'alias';alias.symlink_to(log)
            isolated=AttestationServer(ImaQuoteVerifier(folder/'ak.pem',args.inspector,args.replayer,alias))
            challenge=isolated.issue('client');evidence=fixtures.fixture(challenge,folder,pcrs=pcr,selection=b'\0\4\0')
            result=isolated.submit('client',evidence)
            assert result['decision']=='INDETERMINATE',result
            report['cases'].append('remote_path_forbidden_missing_log_and_symlink_indeterminate')
            # A staged log larger than one network frame remains fully checked.
            data=first*200;log.write_bytes(data);acc=bytes(32)
            for _ in range(200):acc=hashlib.sha256(acc+d1).digest()
            assert len(data)>16384
            challenge=server.issue('client');evidence=fixtures.fixture(challenge,folder,pcrs=acc,selection=b'\0\4\0')
            result=server.submit('client',evidence)
            assert result['decision']=='ALLOW' and result['ima_records']==200,result
            report['cases'].append('complete_staged_log_over_16k_no_network_limit_change')
        report['passed']=True
    except (OSError,ValueError,AssertionError,subprocess.SubprocessError) as error:report['error']=str(error)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
