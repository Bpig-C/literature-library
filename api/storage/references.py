"""Registered PDF references, not arbitrary filesystem URI inputs."""
import re
from .core import StorageError,hash_file
def asset_reference(identity,version=1):
 value=f'litlib-asset://{identity}/pdf/{version}';decode_reference(value);return value
def decode_reference(value):
 m=re.fullmatch(r'litlib-asset://([A-Za-z0-9_-]{1,180})/pdf/([1-9][0-9]*)',str(value))
 if not m:raise StorageError('invalid_request','supported registered PDF reference required')
 return m.group(1),int(m.group(2))
def registered_import(context,reference,work_id,source_file_id,parse_run_id,parse_version):
 from .runtime import configured_service,required_path,enabled
 if not enabled() or context.db_path.resolve()!=required_path('LITLIB_RESEARCH_DB',file=True):raise StorageError('configuration_error','explicit matching immutable research context required')
 identity,pdf_version=decode_reference(reference)
 if identity!=source_file_id or not work_id or not parse_run_id or not isinstance(parse_version,int) or isinstance(parse_version,bool) or parse_version<1:raise StorageError('invalid_request','explicit matching work/source/run/version required')
 service=configured_service()
 with service.registry.conn() as c:
  source=c.execute('SELECT work_id,original_name,content_sha256 FROM source_files WHERE id=?',(identity,)).fetchone()
  parse=c.execute("SELECT source_file_id,work_id FROM literature_parse_runs WHERE id=? AND status='succeeded'",(parse_run_id,)).fetchone()
 if not source or not parse or source['work_id']!=work_id or parse['work_id']!=work_id or parse['source_file_id']!=identity:raise StorageError('invalid_request','registered source/parse ownership mismatch')
 binding=service.registry.binding(identity,'pdf',pdf_version)
 if binding['sha256']!=source['content_sha256']:raise StorageError('checksum_mismatch','catalog PDF fingerprint differs')
 with service.read(identity,'pdf',pdf_version) as pdf,service.read(parse_run_id,'md',parse_version) as md:
  if hash_file(pdf)!=(binding['sha256'],binding['bytes']):raise StorageError('checksum_mismatch','materialized PDF fingerprint differs')
  return {'sha256':binding['sha256'],'original_name':source['original_name'] or identity+'.pdf','text':md.read_text('utf-8')}
