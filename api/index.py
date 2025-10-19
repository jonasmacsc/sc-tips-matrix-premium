import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../')
from app import app as application

def handler(request, response):
    return application(request, response)
