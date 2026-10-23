"""Authenticated encryption for resumable signed URLs; key is environment-only."""
import base64
import hashlib
import os
from .storage.core import StorageError


def key():
    try:
        value=base64.b64decode(os.environ.get('LITLIB_PARSE_UPLOAD_KEY',''),altchars=b'-_',validate=True)
        if len(value)!=32:raise ValueError()
        return value
    except (ValueError,TypeError):raise StorageError('configuration_error','32-byte base64 LITLIB_PARSE_UPLOAD_KEY required for native batches') from None


def key_id():return hashlib.sha256(key()).hexdigest()[:16]


def seal(value,context):
    from Crypto.Cipher import AES
    nonce=os.urandom(12);cipher=AES.new(key(),AES.MODE_GCM,nonce=nonce)
    cipher.update(context.encode());data,tag=cipher.encrypt_and_digest(value.encode())
    return base64.b64encode(nonce+tag+data).decode()


def open_secret(value,context):
    from Crypto.Cipher import AES
    try:
        data=base64.b64decode(value,validate=True)
        cipher=AES.new(key(),AES.MODE_GCM,nonce=data[:12]);cipher.update(context.encode())
        return cipher.decrypt_and_verify(data[28:],data[12:28]).decode()
    except StorageError:raise
    except (ValueError,TypeError,UnicodeError):raise StorageError('configuration_error','signed URL key or recovery envelope differs; inspect without resubmission') from None
