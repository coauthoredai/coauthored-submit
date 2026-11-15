"""WSGI entry point: gunicorn wsgi:app"""
from submit import create_app

app = create_app()
