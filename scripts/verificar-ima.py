"""Bounded IMA SHA256 replay tests and optional local PCR10 comparison.

No raw log, filenames or individual file digests are exported. A local PCR read
is not a signed challenge-bound Quote; consistency is not host trust.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import struct
import subprocess
import tempfile
import time


def field(value): return struct.pack('<I',len(value))+value


def record(subject=b'owned-fixture',name=b'ima-ng',data=None,pcr=10):
    if data is None:
        data=field(b'sha256:\0'+hashlib.sha256(subject).digest())+field(subject+b'\0')
        if name==b'ima-sig':data+=field(b'')
    digest=hashlib.sha256(data).digest()
    return struct.pack('<I',pcr)+digest+field(name)+field(data),digest


def inspect(binary,path):
    result=subprocess.run([str(binary),str(path)],capture_output=True,text=True,timeout=5)
    if result.returncode not in (0,1): raise RuntimeError('PARSER_PROCESS_FAILED')
    if 'AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr: raise RuntimeError('SANITIZER_ERROR')
    value=json.loads(result.stdout)
    if value['parsed']!=(result.returncode==0) or value['attestation_verified']:raise RuntimeError('PARSER_RESULT_INVALID')
    return value


def compare(before,replayed,after):
    if before!=after:return 'INDETERMINATE','PCR_CHANGED_DURING_READ'
    if before!=replayed:return 'DENY','PCR_REPLAY_MISMATCH'
    return 'CONSISTENT','LOCAL_PCR_REPLAY_MATCH'


def offline(binary):
    cases=[]
    with tempfile.TemporaryDirectory(prefix='lab-ima-fixtures-') as directory:
        path=Path(directory)/'log'
        first,d1=record();second,d2=record(b'second-fixture',b'ima-sig')
        expected=hashlib.sha256(hashlib.sha256(bytes(32)+d1).digest()+d2).hexdigest()
        path.write_bytes(first+second);value=inspect(binary,path)
        assert value['parsed'] and value['records']==2 and value['replayed_pcr_sha256']==expected,value
        cases.append('independent_sha256_ng_sig_two_record_replay')
        for data in [first,second+first,first+second+second]:
            path.write_bytes(data);value=inspect(binary,path)
            assert value['parsed'] and compare(expected,value['replayed_pcr_sha256'],expected)==('DENY','PCR_REPLAY_MISMATCH')
        cases.append('deletion_reordering_duplication_fail_expected_pcr')
        for data in [b'',first[:3],first[:35],first[:-1],first+b'x']:
            path.write_bytes(data);assert not inspect(binary,path)['parsed']
        cases.append('empty_truncated_header_payload_trailing_bytes')
        mutated=bytearray(first);mutated[-2]^=1;path.write_bytes(mutated)
        assert inspect(binary,path)['reason']=='TEMPLATE_DIGEST_MISMATCH'
        mutated=bytearray(first);mutated[4:36]=bytes(32);path.write_bytes(mutated)
        assert inspect(binary,path)['reason']=='IMA_VIOLATION'
        cases.append('template_digest_and_violation_rejected')
        invalid=[(record(name=b'ima-unknown')[0],'UNSUPPORTED_TEMPLATE'),(record(pcr=11)[0],'UNSUPPORTED_PCR'),
                 (first[:36]+struct.pack('<I',33),'TEMPLATE_NAME_SIZE'),
                 (first[:46]+struct.pack('<I',65537),'TEMPLATE_DATA_SIZE'),
                 (record(data=struct.pack('<I',100)+b'x')[0],'INVALID_TEMPLATE_FIELDS'),
                 (record(data=field(b'sha256:\0'+bytes(32))+field(b'no-null'))[0],'INVALID_TEMPLATE_FIELDS')]
        for data,reason in invalid:
            path.write_bytes(data);value=inspect(binary,path);assert value['reason']==reason,value
        cases.append('closed_templates_pcr_and_nested_length_limits')
        path.unlink();path.symlink_to(Path(directory)/'missing')
        assert inspect(binary,path)['reason']=='OPEN_ERROR'
        path.unlink();os.mkfifo(path)
        assert inspect(binary,path)['reason']=='NOT_REGULAR_FILE'
        path.unlink();assert inspect(binary,path)['reason']=='OPEN_ERROR'
        cases.append('missing_symlink_fifo_no_block_or_follow')
        generator=random.Random(92026)
        for _ in range(32):
            data=bytearray(first+second)
            for _ in range(generator.randint(1,4)):data[generator.randrange(len(data))]^=generator.randint(1,255)
            path.write_bytes(data);value=inspect(binary,path)
            assert not value['parsed'] or value['replayed_pcr_sha256']==expected
        cases.append('seeded_parser_mutations')
        assert compare('a','a','b')==('INDETERMINATE','PCR_CHANGED_DURING_READ')
        cases.append('changing_pcr_not_accepted')
    return cases


def hardware(binary):
    source=Path('/sys/kernel/security/integrity/ima/binary_runtime_measurements_sha256')
    def read_pcr(path):
        result=subprocess.run(['tpm2_pcrread','-T','device:/dev/tpmrm0','sha256:10','-o',str(path),'-F','values'],capture_output=True,timeout=5)
        if result.returncode:raise RuntimeError('TPM_PCR_READ_FAILED')
        data=path.read_bytes()
        if len(data)!=32:raise RuntimeError('TPM_PCR_SIZE')
        return data.hex()
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='lab-ima-pcr-') as directory:
        before=read_pcr(Path(directory)/'before')
        value=inspect(binary,source)
        after=read_pcr(Path(directory)/'after')
    replayed=value.pop('replayed_pcr_sha256',None)
    if not value['parsed']:return dict(value,assessment='INDETERMINATE')
    assessment,reason=compare(before,replayed,after)
    return dict(value,assessment=assessment,reason=reason,pcr_stable=before==after,
                elapsed_ms=round((time.monotonic()-start)*1000),origin_os='linux',
                evidence_class='self_reported_lab',policy_evaluation='not_performed',
                source_format='sha256-bank little-endian ima-ng/ima-sig',kernel=platform.release())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,default=Path('build/lab_ima_replay'))
    parser.add_argument('--hardware',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();report={'passed':False,'scope':'IMA local replay; not remote attestation','cases':[]}
    try:
        report['cases']=offline(args.binary)
        if args.hardware:
            report['hardware']=hardware(args.binary)
            report['passed']=report['hardware']['assessment']=='CONSISTENT'
        else:report['passed']=True
    except (OSError,ValueError,RuntimeError,AssertionError,subprocess.SubprocessError) as error:report['error']=str(error)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
