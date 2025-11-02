from django.shortcuts import render

# Create your views here.

def signup(request):
    return render(request, 'registration/signup.html')

def index(request):
    return render(request, 'analytics/index.html')