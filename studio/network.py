import ipaddress, socket, os
from urllib.parse import urlparse
import requests
from django.core.exceptions import ValidationError

def validate_url(url, allow_local=False):
    parsed = urlparse(url)
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError('A valid HTTPS URL without embedded credentials is required.')
    allowed = {x.strip() for x in os.getenv('COMFYUI_ALLOWED_HOSTS','').split(',') if x.strip()}
    if allow_local and parsed.hostname in allowed: return url
    if parsed.scheme != 'https': raise ValidationError('Remote connections require HTTPS.')
    try: addresses = socket.getaddrinfo(parsed.hostname,parsed.port or 443,type=socket.SOCK_STREAM)
    except socket.gaierror as exc: raise ValidationError('Destination hostname cannot be resolved.') from exc
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValidationError('Private network destinations are blocked. Explicitly allow a trusted ComfyUI host in COMFYUI_ALLOWED_HOSTS.')
    return url

def request(method,url,**kwargs):
    allow_local = kwargs.pop('allow_local',False)
    validate_url(url,allow_local)
    response = requests.request(method,url,timeout=kwargs.pop('timeout',(15,180)),allow_redirects=False,**kwargs)
    if 300 <= response.status_code < 400: raise ValidationError('Redirects are disabled; configure the final HTTPS endpoint.')
    if response.status_code >= 400:
        # Do not persist provider response bodies, URLs with query credentials, or tokens.
        raise ProviderHTTPError(response.status_code)
    return response

class ProviderHTTPError(Exception):
    def __init__(self,status):
        self.status = status
        super().__init__(f'External service returned HTTP {status}. Check access, configuration and provider limits.')

def download(url):
    response = request('GET',url,stream=True)
    chunks, size = [], 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > 20 * 1024 * 1024: raise ValidationError('Remote image exceeds 20 MB.')
        chunks.append(chunk)
    return b''.join(chunks)
