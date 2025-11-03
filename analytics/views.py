from django.shortcuts import render
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse_lazy
from django.views.generic import CreateView


class SignUpView(CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy("login")
    template_name = "registration/signup.html"

# Create your views here.
#def signup(request):
    #return render(request, 'registration/signup.html')

def index(request):
    return render(request, 'analytics/index.html')

def login(request):
    return render(request, 'analytics/login.html')