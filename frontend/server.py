"""Servidor WSGI para producción bajo IIS (HttpPlatformHandler) o servicio Windows.

Usa waitress y responde al puerto que asigne IIS mediante la variable HTTP_PLATFORM_PORT.
"""
import os
from waitress import serve
from app import app

port = int(os.environ.get('HTTP_PLATFORM_PORT') or os.environ.get('PORT') or 5000)
host = os.environ.get('HOST', '127.0.0.1')

print(f'Dashboard WSGI: http://{host}:{port}')
serve(app, host=host, port=port, threads=6, url_scheme='http')
