from django.shortcuts import render_to_response
from django.http import *

def home(request):
    return HttpResponse('Rajeshi{% hello %}')
