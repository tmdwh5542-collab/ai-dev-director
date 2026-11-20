"""Publisher-only: sign an already-built release. Never uploads or commits anything."""
import argparse,base64,json,os,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core import update_protocol as p


def sign(archive,repository,url,notes,key_path,output):
    key=serialization.load_pem_private_key(Path(key_path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 개인키가 필요합니다.')
    archive=Path(archive)
    with zipfile.ZipFile(archive) as z:manifest=json.loads(z.read('AI DEV DIRECTOR/desktop_distribution.json'))
    payload={'app':p.APP,'format':1,'repository':p.repo(repository),'version':manifest['version'],'min_updater':p.PROTOCOL,'archive_url':p.asset_url(url,repository),'archive_sha256':p.sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,'release_notes':notes}
    envelope={'payload':payload,'signature':base64.b64encode(key.sign(p.canonical(payload))).decode()}
    public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    p.verify_envelope(envelope,public,repository);p.inspect_archive(archive,payload)
    Path(output).write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'feed':str(output),'version':payload['version'],'public_key':public,'uploaded':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',required=True);parser.add_argument('--repository',required=True);parser.add_argument('--asset-url',required=True);parser.add_argument('--notes-file',required=True);parser.add_argument('--private-key',required=True);parser.add_argument('--output',default='director-update.json');args=parser.parse_args()
    print(json.dumps(sign(args.archive,args.repository,args.asset_url,Path(args.notes_file).read_text(encoding='utf-8'),args.private_key,args.output),ensure_ascii=False))
